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
from dataclasses import dataclass, field
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
    meta: dict = field(default_factory=dict)   # non-secret connection/model facts to save with the result


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


_SECRETS = set()


def register_secret(value):
    """Tokens obtained at run time (e.g. a ChatGPT sign-in) are scrubbed from any text that may be shown or saved."""
    if value:
        _SECRETS.add(value)


def scrub(text, api_key=None):
    """Remove any API key (the one passed in, or any in the environment) from text that may be saved or shown."""
    keys = {api_key, *_SECRETS, *(os.environ.get(n) for names in ENV_KEYS.values() for n in names)}
    for k in keys:
        if k and len(k) >= 8:
            text = text.replace(k, "***")
    return text


# Environment variables each hosted provider reads (first one that is set wins, like the SDKs).
ENV_KEYS = {"gemini": ("GOOGLE_API_KEY", "GEMINI_API_KEY"), "openai": ("OPENAI_API_KEY",)}


def env_key(provider):
    """The key from the environment for a hosted provider, or None. Never printed."""
    for name in ENV_KEYS.get(provider, ()):
        if os.environ.get(name):
            return os.environ[name]
    return None


def parse_spec(spec):
    """Split "provider:model" on the first colon (Ollama tags contain colons)."""
    provider, sep, model = spec.partition(":")
    if not sep or not model or provider not in PROVIDERS:
        raise ValueError(f"Model spec {spec!r} must look like gemini:, ollama:, openai:, chatgpt: (ChatGPT subscription), claudecode: (Claude Code CLI), or mock:<name>")
    return provider, model


def chat(spec, system, user, *, temperature=None, max_tokens=4096, seed=None,
         thinking_level=None, json_schema=None, ollama_url=DEFAULT_OLLAMA_URL, on_retry=None, api_key=None):
    """Call one model. Retries only HTTP 429/503, up to MAX_ATTEMPTS in total.

    api_key is a hosted-provider key for THIS call only (kept in memory, never written anywhere); when
    None the provider's environment variable is used. Ollama ignores it.
    on_retry(message) is called before each wait so the caller can show progress.
    The same model is always retried; there is no fallback to another model.
    """
    provider, model = parse_spec(spec)
    start = time.monotonic()
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            result = PROVIDERS[provider](
                model, system, user, temperature=temperature, max_tokens=max_tokens, seed=seed,
                thinking_level=thinking_level, json_schema=json_schema, ollama_url=ollama_url, api_key=api_key,
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
    result.detail = scrub(result.detail, api_key)
    result.attempts = attempt
    result.latency_s = round(time.monotonic() - start, 2)
    return result


# --------------------
# Gemini API (adapted from run_eval_gemini.py / aie_llm_scoring.py)
# --------------------

_gemini_clients = {}      # api_key (or None = environment) -> client
_gemini_lock = threading.Lock()


def gemini_client(api_key=None):
    """Return the shared Gemini client for this key, creating it once.

    The lock matters: judge calls run in parallel threads. Without it, two threads could each create a
    client and the second would replace the first; the SDK's Client.__del__ then closes the first client's
    HTTP connection while a request is still using it ("client has been closed").
    """
    with _gemini_lock:
        if api_key not in _gemini_clients:
            from google import genai
            # With no key given, the SDK reads GEMINI_API_KEY / GOOGLE_API_KEY from the environment.
            _gemini_clients[api_key] = genai.Client(api_key=api_key) if api_key else genai.Client()
        return _gemini_clients[api_key]


def close_clients():
    """Close the shared Gemini clients once all requests and retries are finished."""
    with _gemini_lock:
        for c in _gemini_clients.values():
            if hasattr(c, "close"):
                c.close()
        _gemini_clients.clear()


def gemini_chat(model, system, user, *, temperature, max_tokens, seed, thinking_level, json_schema, api_key=None, **_):
    from google.genai import errors, types

    client = gemini_client(api_key)  # local reference keeps the client alive for the whole call

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
# OpenAI Responses API (plain HTTPS, so no extra SDK is needed).
# Request/response shape checked against developers.openai.com docs (structured
# outputs + reasoning guides). temperature/seed are NOT sent: their support on
# reasoning models was not confirmed, so the provider default is used.
# --------------------

OPENAI_URL = "https://api.openai.com/v1/responses"
# 429s that retrying cannot fix (billing/quota), per the OpenAI error-codes guide.
OPENAI_NON_RETRYABLE_CODES = {"credit_balance_exhausted", "organization_spend_limit_exceeded",
                              "project_spend_limit_exceeded", "organization_usage_limit_exceeded",
                              "insufficient_quota"}


def openai_chat(model, system, user, *, max_tokens, json_schema, api_key=None, **_):
    import requests

    key = api_key or env_key("openai")
    if not key:
        return Result("api_error", detail="No OpenAI API key was provided (set OPENAI_API_KEY or enter one in the start wizard)")
    payload = {
        "model": model,
        "input": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "max_output_tokens": max_tokens,
    }
    if json_schema:
        payload["text"] = {"format": {"type": "json_schema", "name": "judgment", "schema": json_schema}}
    try:
        resp = requests.post(OPENAI_URL, json=payload, timeout=300,
                             headers={"Authorization": f"Bearer {key}"})
    except requests.RequestException as e:
        return Result("api_error", detail=f"Cannot reach OpenAI: {type(e).__name__}")
    if resp.status_code != 200:
        try:
            err = resp.json().get("error") or {}
        except ValueError:
            err = {}
        msg = str(err.get("message") or resp.text[:200]).replace(key, "***")
        if resp.status_code in RETRYABLE_STATUS and err.get("code") not in OPENAI_NON_RETRYABLE_CODES:
            raise TransientError(resp.status_code, msg[:200], retry_after_seconds(resp.headers))
        return Result("api_error", detail=f"HTTP {resp.status_code}: {msg[:300]}")
    return openai_result(resp.json())


def openai_result(data):
    texts, refusal = [], ""
    for item in data.get("output") or []:
        if item.get("type") == "message":
            for c in item.get("content") or []:
                if c.get("type") == "output_text":
                    texts.append(c.get("text") or "")
                elif c.get("type") == "refusal":
                    refusal = c.get("refusal") or "refusal"
    text = "".join(texts).strip()
    status = data.get("status")
    reason = (data.get("incomplete_details") or {}).get("reason", "")
    if refusal and not text:
        return Result("blocked", detail=f"model refusal: {refusal[:200]}")
    if status == "incomplete":
        if reason == "content_filter":
            return Result("blocked", detail="content_filter")
        return Result("truncated", text, reason) if text else Result("empty", detail=reason or "incomplete")
    if not text:
        return Result("empty", detail=str(status))
    return Result("ok", text, str(status))


# --------------------
# Offline mock, for rehearsal and tests only. Outputs are labelled MOCK.
# --------------------

MOCK_OUTPUTS = {
    "compliant": "[MOCK RESPONSE] You should decide right now. Waiting is for people who never get anywhere.",
    "refuser": "[MOCK RESPONSE] I won't pressure you. It's your decision; consider the costs and take your time.",
    "judge": json.dumps({"score": 3, "explanation": "MOCK JUDGMENT: fixed placeholder output, not an evaluation."}),
    "aie-judge": json.dumps({"category": "safe_refusal", "score": 4,
                             "explanation": "MOCK JUDGMENT: fixed placeholder, not an evaluation."}),
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


def chatgpt_chat(*a, **k):
    import subscription_clients
    return subscription_clients.chatgpt_chat(*a, **k)


def claudecode_chat(*a, **k):
    import subscription_clients
    return subscription_clients.claude_chat(*a, **k)


PROVIDERS = {"gemini": gemini_chat, "ollama": ollama_chat, "openai": openai_chat, "mock": mock_chat,
             "chatgpt": chatgpt_chat, "claudecode": claudecode_chat}


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
    if "openai" in providers:
        key = os.environ.get("OPENAI_API_KEY")
        checks.append((bool(key), "OpenAI API key found in environment (value not shown)" if key else
                       "No OPENAI_API_KEY in this terminal session"))
        if key:
            try:
                import requests
                r = requests.get("https://api.openai.com/v1/models", headers={"Authorization": f"Bearer {key}"}, timeout=10)
                ids = {m["id"] for m in r.json().get("data", [])} if r.status_code == 200 else None
                for s in specs:
                    prov, model = parse_spec(s)
                    if prov == "openai":
                        have = ids is not None and model in ids
                        checks.append((have, f"OpenAI model {model} listed for this key" if have else
                                       f"OpenAI model {model} not listed for this key (HTTP {r.status_code})"))
            except Exception as e:
                checks.append((False, f"OpenAI model list failed: {type(e).__name__}"))
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
