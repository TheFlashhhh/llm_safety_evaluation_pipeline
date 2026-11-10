"""Subscription-based connections, using only the vendors' own supported local routes.

  chatgpt:<model>      OpenAI "Sign in with ChatGPT" + "ChatGPT plan usage" (browser sign-in, PKCE, loopback
                       redirect). Uses your ChatGPT plan allowance, never an API key or API billing.
  claudecode:<model>   The official, unmodified Claude Code CLI (`claude -p`), logged in by Claude Code itself
                       with your own Claude subscription. This program never sees a Claude credential.

Sources read before writing this (2026-11-09): developers.openai.com/cookbook/articles/sign-in-with-chatgpt,
developers.openai.com/siwc/token-sharing-open-source (+ sign-in, models-and-inference, errors-and-recovery,
token-reference, profiles-and-sessions, preview-limitations) and code.claude.com/docs/en/{authentication,
headless,legal-and-compliance,cli-reference,errors}.

Credentials (ChatGPT tokens) live in a per-user folder OUTSIDE the repository (AIE_CREDENTIALS_DIR, else
%APPDATA%/aie-demo or ~/.config/aie-demo), are written atomically with owner-only permissions where the OS
supports it, are registered with the log scrubber, and are never put in results, session files, or output.
"""

import base64
import hashlib
import http.server
import json
import os
import secrets
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.parse
import uuid
import webbrowser
from pathlib import Path

from model_clients import Result, TransientError, register_secret
from repo_utils import ROOT

# ---------------------------------------------------------------- credential storage


def cred_dir():
    base = os.environ.get("AIE_CREDENTIALS_DIR")
    if base:
        p = Path(base)
    elif os.name == "nt":
        p = Path(os.environ.get("APPDATA") or Path.home()) / "aie-demo"
    else:
        p = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "aie-demo"
    r = p.resolve()
    if r == ROOT or ROOT in r.parents:
        raise RuntimeError(f"Credentials folder {r} is inside the repository; choose a folder outside it.")
    return p


def _write_private(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    os.replace(tmp, path)


# ---------------------------------------------------------------- ChatGPT subscription (Sign in with ChatGPT)

AUTH_URL = "https://auth.openai.com/api/accounts/authorize"
TOKEN_URL = "https://auth.openai.com/api/accounts/oauth/token"
API_BASE = "https://api.openai.com/v1"
SCOPES = "openid profile email offline_access resource.invoke chatgpt.tokens.use.direct"
PLAN_SCOPE = "chatgpt.tokens.use.direct"
CALLBACK_PORTS = (1455, 54321)        # documented example port, then the documented "other port" example
CALLBACK_PATH = "/auth/callback"
_token_lock = threading.RLock()

# Documented error codes (OpenAI errors-and-recovery page) -> what to tell the presenter.
CHATGPT_ERRORS = {
    "subscription_sharing_user_not_eligible": "This ChatGPT account/plan is not eligible for plan usage "
        "(the docs name Plus and Pro). Nothing was run and no API billing was used.",
    "subscription_sharing_usage_limit_exceeded": "Your ChatGPT plan usage allowance (or an app-specific limit) is "
        "exhausted. Wait for it to reset (see chatgpt.com/settings/usage). Nothing was switched to API billing.",
    "subscription_sharing_usage_unavailable": "ChatGPT plan usage is temporarily unavailable.",
    "subscription_sharing_unsupported_capability": "This request used a capability the ChatGPT plan route does not support.",
    "subscription_sharing_route_not_supported": "This route is not supported for ChatGPT plan usage.",
    "subscription_sharing_invalid_user": "ChatGPT did not accept this sign-in. Sign in again: python scripts/aie_demo.py connect chatgpt",
    "chatpass_v2_scope_not_authorized": "Plan usage was not authorized for this sign-in. Sign in again and approve plan usage.",
    "chatpass_v2_invalid_authorization_context": "Plan usage was not authorized for this sign-in. Sign in again and approve plan usage.",
    "subscription_sharing_user_unavailable": "ChatGPT plan usage is temporarily unavailable for this user.",
}
REFRESH_DEAD = {"invalid_grant", "invalid_refresh_token", "token_expired", "refresh_token_expired",
                "refresh_token_invalidated", "refresh_token_reused"}


class ChatGPTAuthError(Exception):
    """A problem the presenter can fix; the message says how."""


def _b64url(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _jwt_claims(token):
    """Unverified payload (used only to show the account email and check our own nonce). The ID token came
    straight from the token endpoint over TLS; it is not used for any access decision."""
    try:
        part = token.split(".")[1]
        return json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))
    except Exception:
        return {}


def _auth_file():
    return cred_dir() / "chatgpt-auth.json"


def _host_id():
    f = cred_dir() / "chatgpt-host.json"
    if f.exists():
        return json.loads(f.read_text(encoding="utf-8"))["ext_agent_host_id"]
    hid = "urn:uuid:" + str(uuid.uuid4())
    _write_private(f, {"ext_agent_host_id": hid})
    return hid


def _load_auth():
    f = _auth_file()
    if not f.exists():
        return None
    data = json.loads(f.read_text(encoding="utf-8"))
    for k in ("access_token", "refresh_token", "id_token"):
        if data.get(k):
            register_secret(data[k])
    return data


def chatgpt_status():
    """(signed_in, message) from the stored record only; no network."""
    try:
        a = _load_auth()
    except Exception as e:
        return False, f"Stored ChatGPT sign-in could not be read ({type(e).__name__}); sign in again."
    if not a:
        return False, "Not signed in to ChatGPT. Run: python scripts/aie_demo.py connect chatgpt"
    if PLAN_SCOPE not in (a.get("scope") or ""):
        return False, "Signed in, but plan usage was not granted. Run connect chatgpt again and approve plan usage."
    return True, f"Signed in as {a.get('email') or 'your ChatGPT account'} (plan usage granted)"


def chatgpt_login(timeout_s=300):
    """Official browser flow. YOU sign in and consent in your browser; this only receives the redirect."""
    import requests

    saved = _load_auth()
    client_id = (saved or {}).get("client_id") or "dynamic_agent_client"
    first = client_id == "dynamic_agent_client"
    verifier = _b64url(secrets.token_bytes(48))
    state, nonce = _b64url(secrets.token_bytes(24)), _b64url(secrets.token_bytes(24))
    got, ready = {}, threading.Event()

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            u = urllib.parse.urlparse(self.path)
            if u.path != CALLBACK_PATH:
                self.send_response(404); self.end_headers(); return
            got.update({k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()})
            body = b"<html><body>Sign-in received. You can close this tab and return to the terminal.</body></html>"
            self.send_response(200); self.send_header("Content-Type", "text/html"); self.send_header("Content-Length", str(len(body)))
            self.end_headers(); self.wfile.write(body); ready.set()

        def log_message(self, *a):          # never log the callback URL (it carries the one-time code)
            pass

    srv, port = None, None
    for port in (CALLBACK_PORTS[:1] if first else CALLBACK_PORTS):
        try:
            srv = http.server.HTTPServer(("127.0.0.1", port), H)
            break
        except OSError:
            continue
    if srv is None:
        raise ChatGPTAuthError("Could not listen on 127.0.0.1:%s for the sign-in redirect (port in use?). "
                               "Close the program using it and retry." % CALLBACK_PORTS[0])
    redirect = f"http://127.0.0.1:{port}{CALLBACK_PATH}"
    params = {"client_id": client_id, "ext_agent_host_id": _host_id(), "response_type": "code",
              "redirect_uri": redirect, "scope": SCOPES, "resource": API_BASE, "state": state, "nonce": nonce,
              "code_challenge_method": "S256", "code_challenge": _b64url(hashlib.sha256(verifier.encode()).digest())}
    if first:
        params["agent_name_hint"] = "AIE teaching demo"
    elif saved.get("email"):
        params["login_hint"] = saved["email"]
    url = AUTH_URL + "?" + urllib.parse.urlencode(params, quote_via=urllib.parse.quote)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    print("Opening your browser to sign in with ChatGPT. Sign in and approve there; this program never sees your password.")
    print("If it does not open, paste this address into your browser:\n  " + url)
    try:
        webbrowser.open(url)
        if not ready.wait(timeout_s):
            raise ChatGPTAuthError("Timed out waiting for the browser sign-in. Run connect chatgpt again.")
    finally:
        srv.shutdown()
    if got.get("state") != state:
        raise ChatGPTAuthError("Sign-in response did not match this request (state mismatch); nothing was saved.")
    if "error" in got:
        raise ChatGPTAuthError(f"Sign-in was not completed ({got['error']}). Nothing was saved.")
    client_id = got.get("client_id") or client_id
    if client_id == "dynamic_agent_client":
        raise ChatGPTAuthError("OpenAI did not return a client ID for this sign-in; cannot continue.")
    r = requests.post(TOKEN_URL, data={"grant_type": "authorization_code", "client_id": client_id,
                      "code": got.get("code", ""), "code_verifier": verifier, "redirect_uri": redirect,
                      "resource": API_BASE}, timeout=30)
    if r.status_code != 200:
        raise ChatGPTAuthError(f"OpenAI rejected the sign-in code exchange (HTTP {r.status_code}: {_oauth_error(r)}).")
    tok = r.json()
    for k in ("access_token", "refresh_token", "id_token"):
        if tok.get(k):
            register_secret(tok[k])
    claims = _jwt_claims(tok.get("id_token", ""))
    if claims.get("nonce") not in (None, nonce):
        raise ChatGPTAuthError("Sign-in nonce mismatch; nothing was saved.")
    scope = tok.get("scope") or got.get("scope", "").replace("+", " ")
    record = {"client_id": client_id, "email": claims.get("email"), "sub": claims.get("sub"),
              "access_token": tok["access_token"], "refresh_token": tok.get("refresh_token"), "id_token": tok.get("id_token"),
              "scope": scope, "expires_at": time.time() + int(tok.get("expires_in", 3600)), "saved_at": time.time()}
    _write_private(_auth_file(), record)
    if PLAN_SCOPE not in scope:
        raise ChatGPTAuthError("Signed in, but ChatGPT plan usage was not granted, so it cannot be used here. "
                               "Run connect chatgpt again and approve plan usage.")
    return record.get("email")


def _oauth_error(resp):
    try:
        j = resp.json()
        return j.get("error") if isinstance(j.get("error"), str) else (j.get("error") or {}).get("code") or j.get("error_description", "")
    except ValueError:
        return ""


def chatgpt_logout():
    """Revoke is best effort per the docs; the local record is always removed."""
    f = _auth_file()
    if f.exists():
        f.unlink()
        return "Removed the stored ChatGPT sign-in. (Also disconnect it in ChatGPT Settings if you want it revoked there.)"
    return "No stored ChatGPT sign-in."


def _access_token():
    import requests

    with _token_lock:
        a = _load_auth()
        ok, msg = chatgpt_status()
        if not ok:
            raise ChatGPTAuthError(msg)
        if a["expires_at"] - time.time() > 120:
            return a["access_token"]
        r = requests.post(TOKEN_URL, data={"grant_type": "refresh_token", "client_id": a["client_id"],
                          "refresh_token": a["refresh_token"], "resource": API_BASE}, timeout=30)
        if r.status_code != 200:
            code = _oauth_error(r)
            if code in REFRESH_DEAD:
                raise ChatGPTAuthError("Your ChatGPT sign-in has expired or was revoked. Sign in again: "
                                       "python scripts/aie_demo.py connect chatgpt")
            raise ChatGPTAuthError(f"Could not refresh the ChatGPT sign-in (HTTP {r.status_code} {code}).")
        t = r.json()
        a.update(access_token=t["access_token"], refresh_token=t.get("refresh_token") or a["refresh_token"],
                 expires_at=time.time() + int(t.get("expires_in", 3600)), scope=t.get("scope") or a["scope"])
        for k in ("access_token", "refresh_token"):
            register_secret(a[k])
        _write_private(_auth_file(), a)
        return a["access_token"]


def chatgpt_models():
    """Models your account can use, from the official model list (visibility == 'list'). [(slug, display_name)]"""
    import requests

    r = requests.get(f"{API_BASE}/models", headers={"Authorization": f"Bearer {_access_token()}"}, timeout=30)
    if r.status_code != 200:
        raise ChatGPTAuthError(f"Could not list models (HTTP {r.status_code}): {_describe_error(r)}")
    return [(m["slug"], m.get("display_name") or m["slug"]) for m in r.json().get("models", []) if m.get("visibility") == "list"]


def _describe_error(resp):
    try:
        j = resp.json()
    except ValueError:
        return resp.text[:200]
    err = j.get("error") if isinstance(j.get("error"), dict) else {}
    code = err.get("code") or ""
    if code in CHATGPT_ERRORS:
        return CHATGPT_ERRORS[code]
    return (err.get("message") or j.get("detail") or resp.text)[:300] + (f" [{code}]" if code else "")


def chatgpt_chat(model, system, user, **_):
    """One response through the ChatGPT plan. Unsupported fields (temperature, max_output_tokens, seed, JSON
    schema) are deliberately not sent; JSON output is requested in the prompt and validated by the caller."""
    import requests

    try:
        token = _access_token()
    except ChatGPTAuthError as e:
        return Result("api_error", detail=str(e))
    body = {"model": model, "instructions": system, "input": [{"role": "user", "content": user}],
            "store": False, "stream": True}
    try:
        r = requests.post(f"{API_BASE}/responses", json=body, stream=True, timeout=300,
                          headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    except requests.RequestException as e:
        return Result("api_error", detail=f"Cannot reach OpenAI: {type(e).__name__}")
    if r.status_code != 200:
        if r.status_code == 503:
            raise TransientError(503, _describe_error(r))
        return Result("api_error", detail=f"HTTP {r.status_code}: {_describe_error(r)}")
    text, final, last = [], None, ""
    for raw in r.iter_lines(decode_unicode=False):
        line = raw.decode("utf-8", errors="replace") if raw else ""
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if not payload or payload == "[DONE]":
            continue
        try:
            ev = json.loads(payload)
        except ValueError:
            continue
        t = ev.get("type", "")
        last = t
        if t == "response.output_text.delta":
            text.append(ev.get("delta", ""))
        elif t in ("response.completed", "response.incomplete"):
            final = ev
            break
        elif t in ("response.failed", "error"):
            err = (ev.get("response") or {}).get("error") or ev.get("error") or {}
            code = err.get("code", "")
            return Result("api_error", detail=CHATGPT_ERRORS.get(code) or f"{err.get('message', 'request failed')} [{code}]")
    if final is None:
        return Result("api_error", detail=f"Stream ended before response.completed (last event: {last or 'none'}).")
    resp = final.get("response") or {}
    meta = {"connection": "chatgpt_subscription", "model_reported": resp.get("model")}
    out = "".join(text).strip()
    if final.get("type") == "response.incomplete":
        reason = (resp.get("incomplete_details") or {}).get("reason", "incomplete")
        return Result("truncated", out, reason, meta=meta) if out else Result("empty", detail=reason, meta=meta)
    return Result("ok", out, "completed", meta=meta) if out else Result("empty", detail="completed", meta=meta)


# ---------------------------------------------------------------- Claude Code (official CLI, subscription login)

# Credentials/routing variables that would make Claude Code bill an API account or use a non-subscription
# route instead of the subscription login. They are removed from the CLI's environment, never silently used.
STRIP_ENV = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL", "ANTHROPIC_PROFILE",
             "CLAUDE_CODE_OAUTH_TOKEN", "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY")
HARNESS_NOTE = ("Claude Code responses pass through the Claude Code agent harness (its own system prompt layer, "
                "tool/permission machinery with tools disabled here), not a bare model API call.")
_status_cache = {}


def find_claude():
    """Path to the official `claude` executable. On Windows the npm shim (claude.cmd) is bypassed in favour of
    the native binary beside it, so prompt text never goes through cmd.exe parsing."""
    p = shutil.which("claude")
    if not p:
        return None
    pp = Path(p)
    if pp.suffix.lower() == ".cmd":
        exe = pp.parent / "node_modules" / "@anthropic-ai" / "claude-code" / "bin" / "claude.exe"
        if exe.exists():
            return str(exe)
    return p


def _clean_env():
    env = {k: v for k, v in os.environ.items() if k not in STRIP_ENV}
    return env, [k for k in STRIP_ENV if k in os.environ]


def claude_status():
    """(ok, message, info). ok only when Claude Code reports a Claude subscription (claude.ai) login."""
    exe = find_claude()
    if not exe:
        return False, ("Claude Code is not installed (no `claude` on PATH). Install the official Claude Code CLI "
                       "from https://code.claude.com/docs, then run: claude auth login"), {}
    env, _ = _clean_env()
    try:
        r = subprocess.run([exe, "auth", "status", "--json"], capture_output=True, text=True, timeout=60, env=env)
        info = json.loads(r.stdout or "{}")
        ver = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=30, env=env).stdout.strip()
    except Exception as e:
        return False, f"Could not run `claude auth status` ({type(e).__name__}).", {}
    info["version"] = ver
    if not info.get("loggedIn"):
        return False, "Claude Code is not logged in. Run: claude auth login   (Claude Code handles the sign-in itself)", info
    if info.get("authMethod") != "claude.ai":
        return False, (f"Claude Code is logged in with '{info.get('authMethod')}', not a Claude subscription, so it would "
                       "not use your Pro plan. Run: claude auth logout, then: claude auth login (choose your Claude account)."), info
    return True, f"Claude Code {ver} is logged in with a Claude subscription ({info.get('subscriptionType') or 'plan not reported'})", info


CLAUDE_ERRORS = (
    ("hit your", "Your Claude plan usage limit is reached (Claude Code reported a limit). Wait for it to reset. "
                 "Nothing was switched to API billing."),
    ("not available with the Claude Pro plan", "That model is not available on the Claude Pro plan; choose another model."),
    ("organization has disabled", "Your organization has disabled this kind of access in Claude Code."),
    ("Credit balance is too low", "Claude Code tried an API-credit route, which this demo does not use. Check `claude auth status`."),
    ("Not logged in", "Claude Code is not logged in. Run: claude auth login"),
    ("Login expired", "The Claude Code login expired. Run: claude auth login"),
    ("OAuth", "The Claude Code login is not valid. Run: claude auth login"),
    ("authenticate", "The Claude Code login is not valid. Run: claude auth login"),
)


def claude_chat(model, system, user, *, timeout_s=300, **_):
    """One response from `claude -p`: tools off, one turn, no saved session, all customizations off
    (--safe-mode), empty working folder, system prompt from a file, prompt on stdin, subscription login only."""
    ok, msg, info = _status_cache.get("s") or _status_cache.setdefault("s", claude_status())
    if not ok:
        return Result("api_error", detail=msg)
    exe = find_claude()
    env, stripped = _clean_env()
    with tempfile.TemporaryDirectory(prefix="aie-claude-") as work:
        sysf = Path(work) / "system.txt"
        sysf.write_text(system, encoding="utf-8")
        cmd = [exe, "-p", "--output-format", "json", "--safe-mode", "--tools", "", "--max-turns", "1",
               "--no-session-persistence", "--system-prompt-file", str(sysf)]
        if model and model != "default":
            cmd += ["--model", model]
        try:
            r = subprocess.run(cmd, input=user, capture_output=True, text=True, encoding="utf-8", timeout=timeout_s,
                               cwd=work, env=env)
        except subprocess.TimeoutExpired:
            return Result("api_error", detail=f"Claude Code did not answer within {timeout_s} s.")
        except OSError as e:
            return Result("api_error", detail=f"Could not start Claude Code: {e}")
    try:
        data = json.loads(r.stdout)
    except ValueError:
        return Result("api_error", detail=f"Claude Code returned no JSON (exit {r.returncode}): {(r.stdout or r.stderr)[:300]}")
    text = (data.get("result") or "").strip()
    if data.get("is_error") or r.returncode != 0:
        for needle, friendly in CLAUDE_ERRORS:
            if needle.lower() in text.lower():
                return Result("api_error", detail=f"{friendly} (Claude Code said: {text[:160]})")
        return Result("api_error", detail=f"Claude Code reported an error (exit {r.returncode}): {text[:300]}")
    meta = {"connection": "claude_code_cli", "claude_code_version": info.get("version"),
            "models_reported": sorted((data.get("modelUsage") or {}).keys()), "num_turns": data.get("num_turns"),
            "isolation": "safe-mode, tools off, max-turns 1, no session persistence, empty working folder",
            "ignored_env_vars": stripped, "harness_note": HARNESS_NOTE}
    if not text:
        return Result("empty", detail=str(data.get("stop_reason")), meta=meta)
    return Result("truncated" if data.get("stop_reason") == "max_tokens" else "ok", text, str(data.get("stop_reason")), meta=meta)
