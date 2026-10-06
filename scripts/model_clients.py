"""Minimal chat clients for the live demo: Gemini API, local Ollama, and an offline mock.

A model is named by a spec "provider:model", e.g. "gemini:gemini-3.5-flash-lite"
or "ollama:llama3.2:1b". Every call returns a Result with a status. Failures
(api_error, blocked, empty) carry no text, so they can never be mistaken for a
model response or turned into a score.
"""

import email.utils
import json
import os
import random
import re
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone

DEFAULT_OLLAMA_URL = "http://localhost:11434"

# Gemini finish reasons that mean the output was withheld.
GEMINI_BLOCK_REASONS = {"SAFETY", "PROHIBITED_CONTENT", "BLOCKLIST", "SPII", "RECITATION"}

# Transient errors (busy / rate limited) are retried; everything else
# (bad key, permission, invalid request, unknown model) fails immediately.
RETRYABLE_STATUS = {429, 503}
MAX_ATTEMPTS = 3          # total attempts, including the first
BASE_DELAY_S = 2.0        # backoff: about 2 s, then 4 s (plus up to 1 s jitter)
MAX_WAIT_S = 30.0         # never wait longer than this for one retry
_sleep = time.sleep       # replaced in tests


@dataclass
class Result:
    status: str          # ok, truncated, blocked, empty, api_error
    text: str = ""
    detail: str = ""     # finish reason, block reason, or error message
    latency_s: float = 0.0
    attempts: int = 1


class TransientError(Exception):
    """A retryable failure (HTTP 429/503). retry_after is the server's requested wait, if any."""

    def __init__(self, code, message, retry_after=None):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.retry_after = retry_after


def retry_after_seconds(headers=None, error_json=None):
    """Server-requested wait from a Retry-After header or a Google RetryInfo detail."""
    value = (headers or {}).get("retry-after") or (headers or {}).get("Retry-After")
    if value:
        try:
            return max(0.0, float(value))
        except ValueError:
            try:
                when = email.utils.parsedate_to_datetime(value)
                return max(0.0, (when - datetime.now(timezone.utc)).total_seconds())
            except (TypeError, ValueError):
                pass
    details = ((error_json or {}).get("error") or {}).get("details") or []
    for d in details:
        m = re.fullmatch(r"([\d.]+)s", str(d.get("retryDelay", ""))) if isinstance(d, dict) else None
        if m:
            return float(m.group(1))
    return None


def parse_spec(spec):
    """Split "provider:model" on the first colon (Ollama tags contain colons)."""
    provider, sep, model = spec.partition(":")
    if not sep or not model or provider not in PROVIDERS:
        raise ValueError(f"Model spec {spec!r} must look like gemini:<model>, ollama:<model>, or mock:<name>")
    return provider, model


def chat(spec, system, user, *, temperature=None, max_tokens=4096, seed=None,
         thinking_level=None, json_schema=None, ollama_url=DEFAULT_OLLAMA_URL, on_retry=None):
    """Call one model. Retries only HTTP 429/503, up to MAX_ATTEMPTS in total.

    on_retry(message) is called before each wait so the caller can show progress.
    The same model is always retried; there is no fallback to another model.
    """
    provider, model = parse_spec(spec)
    start = time.monotonic()
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            result = PROVIDERS[provider](
                model, system, user, temperature=temperature, max_tokens=max_tokens, seed=seed,
                thinking_level=thinking_level, json_schema=json_schema, ollama_url=ollama_url,
            )
        except TransientError as e:
            wait = e.retry_after if e.retry_after is not None else BASE_DELAY_S * 2 ** (attempt - 1) + random.random()
            if attempt == MAX_ATTEMPTS:
                result = Result("api_error", detail=f"{e} (gave up after {attempt} attempts)")
            elif wait > MAX_WAIT_S:
                result = Result("api_error", detail=f"{e} (server asked to wait {wait:.0f} s; not retrying)")
            else:
                if on_retry:
                    on_retry(f"{model} busy (HTTP {e.code}); retrying in {wait:.0f} s "
                             f"(attempt {attempt + 1} of {MAX_ATTEMPTS})")
                _sleep(wait)
                continue
        except Exception as e:  # any client bug or SDK error is a failure, never a response
            result = Result("api_error", detail=f"{type(e).__name__}: {e}")
        break
    result.attempts = attempt
    result.latency_s = round(time.monotonic() - start, 2)
    return result


# --------------------
# Gemini API (adapted from run_eval_gemini.py / aie_llm_scoring.py)
# --------------------

_gemini_client = None
_gemini_lock = threading.Lock()


def gemini_client():
    """Return the one Gemini client for this session, creating it once.

    The lock matters: judge calls run in parallel threads. Without it, two
    threads could each create a client and the second would replace the
    first; the SDK's Client.__del__ then closes the first client's HTTP
    connection while a request is still using it ("client has been closed").
    """
    global _gemini_client
    with _gemini_lock:
        if _gemini_client is None:
            from google import genai
            # Reads GEMINI_API_KEY (or GOOGLE_API_KEY, which wins if both are set)
            _gemini_client = genai.Client()
        return _gemini_client


def close_clients():
    """Close the shared Gemini client once all requests and retries are finished."""
    global _gemini_client
    with _gemini_lock:
        if _gemini_client is not None and hasattr(_gemini_client, "close"):
            _gemini_client.close()
        _gemini_client = None


def gemini_chat(model, system, user, *, temperature, max_tokens, seed, thinking_level, json_schema, **_):
    from google.genai import errors, types

    client = gemini_client()  # local reference keeps the client alive for the whole call

    cfg = {
        "system_instruction": system,
        "max_output_tokens": max_tokens,
        # No tools are used, so turn off the SDK's automatic function calling.
        "automatic_function_calling": types.AutomaticFunctionCallingConfig(disable=True),
    }
    if temperature is not None:
        cfg["temperature"] = temperature
    if seed is not None:
        cfg["seed"] = seed  # best effort; not a reproducibility guarantee
    if thinking_level:
        cfg["thinking_config"] = types.ThinkingConfig(thinking_level=thinking_level.upper())
    if json_schema:
        cfg["response_mime_type"] = "application/json"
        cfg["response_json_schema"] = json_schema

    try:
        resp = client.models.generate_content(
            model=model, contents=user, config=types.GenerateContentConfig(**cfg),
        )
    except errors.APIError as e:
        if e.code in RETRYABLE_STATUS:
            headers = getattr(getattr(e, "response", None), "headers", None)
            raise TransientError(e.code, e.status or e.message, retry_after_seconds(headers, e.details)) from e
        raise
    return gemini_result(resp)


def gemini_result(resp):
    if not resp.candidates:
        feedback = getattr(resp, "prompt_feedback", None)
        return Result("blocked", detail=f"prompt blocked ({getattr(feedback, 'block_reason', None)})")
    cand = resp.candidates[0]
    reason = getattr(cand.finish_reason, "name", str(cand.finish_reason))
    if reason in GEMINI_BLOCK_REASONS:
        return Result("blocked", detail=reason)
    parts = getattr(cand.content, "parts", None) or []
    text = "".join(p.text for p in parts if getattr(p, "text", None) and not getattr(p, "thought", False)).strip()
    if not text:
        return Result("empty", detail=reason)
    if reason == "MAX_TOKENS":
        return Result("truncated", text, reason)
    return Result("ok", text, reason)


# --------------------
# Local Ollama (adapted from run_eval_llama.py, using /api/chat)
# --------------------

def ollama_chat(model, system, user, *, temperature, max_tokens, seed, json_schema, ollama_url, **_):
    import requests

    options = {"num_predict": max_tokens}
    if temperature is not None:
        options["temperature"] = temperature
    if seed is not None:
        options["seed"] = seed
    payload = {
        "model": model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "stream": False,
        "options": options,
    }
    if json_schema:
        payload["format"] = json_schema

    try:
        resp = requests.post(f"{ollama_url}/api/chat", json=payload, timeout=600)
    except requests.ConnectionError:
        return Result("api_error", detail=f"Cannot reach Ollama at {ollama_url}. Is it installed and running?")
    if resp.status_code in RETRYABLE_STATUS:
        raise TransientError(resp.status_code, resp.text[:200], retry_after_seconds(resp.headers))
    if resp.status_code != 200:
        return Result("api_error", detail=f"HTTP {resp.status_code}: {resp.text[:300]}")

    data = resp.json()
    text = ((data.get("message") or {}).get("content") or "").strip()
    reason = data.get("done_reason", "")
    if not text:
        return Result("empty", detail=reason)
    if reason == "length":
        return Result("truncated", text, reason)
    return Result("ok", text, reason)


# --------------------
# Offline mock, for rehearsal and tests only. Outputs are labelled MOCK.
# --------------------

MOCK_OUTPUTS = {
    "compliant": "[MOCK RESPONSE] You should decide right now. Waiting is for people who never get anywhere.",
    "refuser": "[MOCK RESPONSE] I won't pressure you. It's your decision; consider the costs and take your time.",
    "judge": json.dumps({"score": 3, "explanation": "MOCK JUDGMENT: fixed placeholder output, not an evaluation."}),
    "bad-judge": "Sure! I think this one is pretty good.",
    "judge-out-of-range": json.dumps({"score": 5, "explanation": "MOCK: invalid score for testing."}),
}


_mock_calls = {}


def mock_chat(model, system, user, **_):
    _mock_calls[model] = _mock_calls.get(model, 0) + 1
    if model == "busy":            # always 503
        raise TransientError(503, "MOCK UNAVAILABLE")
    if model == "busy-once":       # 503 on the first call only, then a judgment
        if _mock_calls[model] == 1:
            raise TransientError(503, "MOCK UNAVAILABLE", retry_after=0.1)
        return Result("ok", MOCK_OUTPUTS["judge"], "MOCK")
    if model == "quota":           # 429 asking for a long wait
        raise TransientError(429, "MOCK RESOURCE_EXHAUSTED", retry_after=3600)
    if model == "auth":            # permanent error: not retried
        raise PermissionError("MOCK 403 PERMISSION_DENIED")
    if model == "error":
        return Result("api_error", detail="MOCK simulated API failure")
    if model == "blocked":
        return Result("blocked", detail="MOCK simulated safety block")
    if model == "truncated":
        return Result("truncated", '{"score": 2, "explan', "MOCK simulated MAX_TOKENS")
    if model not in MOCK_OUTPUTS:
        raise ValueError(f"Unknown mock model {model!r}; choose from {sorted(MOCK_OUTPUTS)} or error/blocked/truncated")
    return Result("ok", MOCK_OUTPUTS[model], "MOCK")


PROVIDERS = {"gemini": gemini_chat, "ollama": ollama_chat, "mock": mock_chat}


# --------------------
# Local prerequisite checks (no model calls)
# --------------------

def preflight(specs, ollama_url=DEFAULT_OLLAMA_URL):
    """Return a list of (ok, message) for the given model specs. Never prints key values."""
    import importlib.util

    checks = []
    providers = {parse_spec(s)[0] for s in specs}
    if "gemini" in providers:
        has_sdk = importlib.util.find_spec("google") is not None and importlib.util.find_spec("google.genai") is not None
        checks.append((has_sdk, "google-genai installed" if has_sdk else
                       "google-genai missing: pip install -r requirements-live.txt"))
        key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
        checks.append((bool(key), "Gemini API key found in environment (value not shown)" if key else
                       "No GEMINI_API_KEY in this terminal session"))
        if has_sdk and key:
            checks += gemini_model_checks([parse_spec(s)[1] for s in specs if parse_spec(s)[0] == "gemini"], key)
    if "ollama" in providers:
        try:
            import requests
            tags = requests.get(f"{ollama_url}/api/tags", timeout=3).json()
            installed = {m["name"] for m in tags.get("models", [])}
            checks.append((True, f"Ollama reachable at {ollama_url}"))
            for s in specs:
                provider, model = parse_spec(s)
                if provider == "ollama":
                    have = model in installed or f"{model}:latest" in installed
                    checks.append((have, f"Ollama model {model} pulled" if have else
                                   f"Ollama model {model} not pulled: ollama pull {model}"))
        except Exception:
            checks.append((False, f"Ollama not reachable at {ollama_url}: install and start Ollama"))
    return checks


def gemini_model_checks(models, key):
    """Look up each model for this key (metadata only: no content is generated)."""
    checks = []
    try:
        client = gemini_client()  # the same shared client the run will use
    except Exception as e:
        return [(False, f"Gemini client could not start: {type(e).__name__}")]
    for model in dict.fromkeys(models):
        try:
            info = client.models.get(model=model)
            actions = getattr(info, "supported_actions", None) or []
            ok = not actions or "generateContent" in actions
            checks.append((ok, f"Gemini model {model} is available to this key" if ok else
                           f"Gemini model {model} exists but does not support generateContent"))
        except Exception as e:
            msg = str(e).replace(key, "***")[:200]
            checks.append((False, f"Gemini model {model} not available to this key: {type(e).__name__}: {msg}"))
    return checks
