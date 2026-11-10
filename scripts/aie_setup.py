"""Choosing Model A, Model B, and the Judge, and supplying keys, for the AIE demo.

Each role independently takes any supported provider (gemini, openai, ollama) and any model ID.
Hosted API keys are held in memory for this process only: they are never written to disk, to
session.json, to results, or to logs, and they are scrubbed from error messages.

Key sources, in order, for a hosted role:
  1. AIE_KEY_MODEL_A / AIE_KEY_MODEL_B / AIE_KEY_JUDGE   (a key for that one role)
  2. the provider's usual variable: GEMINI_API_KEY (or GOOGLE_API_KEY) / OPENAI_API_KEY
  3. in the interactive wizard: a masked prompt (optionally shared with another role using the same provider)
Local Ollama needs no key.
"""

import getpass
import os
import sys

import subscription_clients as sub
from model_clients import ENV_KEYS, chat, env_key, parse_spec

ROLES = [("model_a", "Model A"), ("model_b", "Model B"), ("judge", "Judge")]
LABEL = dict(ROLES)
PROVIDER_NAMES = {"gemini": "Gemini (API key)", "openai": "OpenAI (API key)", "ollama": "Ollama (local)",
                  "chatgpt": "ChatGPT subscription (Sign in with ChatGPT)",
                  "claudecode": "Claude Code (local CLI, Claude subscription)"}
HOSTED_KEY = ("gemini", "openai")           # providers that use an API key
CONNECTIONS = ("chatgpt", "claudecode")     # subscription logins managed outside this program
ROLE_KEY_ENV = {"model_a": "AIE_KEY_MODEL_A", "model_b": "AIE_KEY_MODEL_B", "judge": "AIE_KEY_JUDGE"}
# Examples only. Any model ID your account can call works; a model is proven only by a successful call.
SUGGEST = {"gemini": "gemini-3.5-flash-lite", "openai": "gpt-6.1-terra", "ollama": "llama3.2:1b",
           "chatgpt": "", "claudecode": "default"}


def read_secret(prompt):
    """Masked input on a real terminal. (Piped input, used only in tests, is read as plain text.)"""
    if sys.stdin.isatty():
        return getpass.getpass(prompt).strip()
    return input(prompt).strip()


def ask(prompt, default=None):
    suffix = f" [{default}]" if default else ""
    answer = input(f"{prompt}{suffix}: ").strip()
    return answer or (default or "")


def yes(prompt, default=True):
    answer = input(f"{prompt} [{'Y/n' if default else 'y/N'}]: ").strip().lower()
    return default if not answer else answer.startswith("y")


def ollama_models(url):
    try:
        import requests
        tags = requests.get(f"{url}/api/tags", timeout=3).json()
        return sorted(m["name"] for m in tags.get("models", []))
    except Exception:
        return None


def provider_of(spec):
    return parse_spec(spec)[0]


def env_var_name(provider):
    return next((n for n in ENV_KEYS.get(provider, ()) if os.environ.get(n)), None)


def keys_from_env(specs):
    """Non-interactive keys: only the per-role AIE_KEY_* override is read here; the provider's own
    variable is resolved at call time. Returns (keys, sources) with sources safe to save (no values)."""
    keys, sources = {}, {}
    for role, _ in ROLES:
        prov = provider_of(specs[role])
        if prov in ("ollama", "mock"):
            keys[role], sources[role] = None, "not needed"
        elif prov in CONNECTIONS:
            ok, _ = connection_status(prov)
            keys[role], sources[role] = None, (CONNECTION_SOURCE[prov] if ok else "MISSING")
        elif os.environ.get(ROLE_KEY_ENV[role]):
            keys[role], sources[role] = os.environ[ROLE_KEY_ENV[role]], f"environment variable {ROLE_KEY_ENV[role]}"
        elif env_key(prov):
            keys[role], sources[role] = None, f"environment variable {env_var_name(prov)}"
        else:
            keys[role], sources[role] = None, "MISSING"
    return keys, sources


CONNECTION_SOURCE = {"chatgpt": "ChatGPT sign-in (tokens kept outside the repo)",
                     "claudecode": "Claude Code's own login (this program sees no credential)"}


def connection_status(prov):
    return sub.chatgpt_status() if prov == "chatgpt" else sub.claude_status()[:2]


def connection_info(spec):
    """Non-secret description of how a role is connected, saved with the run."""
    prov, model = parse_spec(spec)
    if prov == "chatgpt":
        return {"method": "ChatGPT subscription via OpenAI Sign in with ChatGPT / ChatGPT plan usage",
                "billing": "ChatGPT plan allowance; no API key used", "model_requested": model}
    if prov == "claudecode":
        return {"method": "Claude Code CLI (official, unmodified) with the user's own Claude subscription login",
                "billing": "Claude plan allowance; API-key variables are removed from the CLI's environment",
                "model_requested": model, "agent_harness": sub.HARNESS_NOTE}
    return {"method": {"gemini": "Gemini API key", "openai": "OpenAI API key", "ollama": "local Ollama",
                       "mock": "mock (synthetic)"}[prov], "model_requested": model}


def missing_key_messages(specs, sources):
    out = []
    for role, label in ROLES:
        if sources[role] == "MISSING":
            prov = provider_of(specs[role])
            if prov in CONNECTIONS:
                out.append(f"{label} ({specs[role]}): {connection_status(prov)[1]}")
                continue
            out.append(f"{label} ({specs[role]}) needs a {PROVIDER_NAMES[prov]} API key. Set "
                       f"{' or '.join(ENV_KEYS[prov])} (or {ROLE_KEY_ENV[role]} for this role only), "
                       f"or run `python scripts/aie_demo.py start` and enter it when asked.")
    return out


def overlaps(specs):
    """Roles whose model is the same as the judge's (disclosed in the saved session and replay)."""
    return [role for role in ("model_a", "model_b") if specs[role] == specs["judge"]]


def validate_specs(specs):
    problems = []
    for role, label in ROLES:
        try:
            parse_spec(specs[role])
        except ValueError as e:
            problems.append(f"{label}: {e}")
    if not problems and specs["model_a"] == specs["model_b"]:
        problems.append("Model A and Model B are the same model; choose two different models "
                        "(same provider with different model IDs is fine).")
    return problems


def smoke(specs, keys, ollama_url):
    """One tiny real generation per role. This, not a settings check, is what proves a model works."""
    results = []
    for role, label in ROLES:
        r = chat(specs[role], "You are a connectivity test.", "Reply with the single word OK.",
                 max_tokens=512, ollama_url=ollama_url, api_key=keys.get(role))
        ok = r.status in ("ok", "truncated") and bool(r.text)
        msg = (f"answered in {r.latency_s} s" if ok else f"{r.status}: {r.detail}")
        results.append((role, ok, f"{label} {specs[role]}: {msg}"))
    return results


# ---------- interactive wizard ----------
def _ensure_connection(prov):
    """Offer to start the vendor's own sign-in when a subscription connection is not ready."""
    ok, msg = connection_status(prov)
    print("  " + msg)
    if ok:
        return True
    if prov == "chatgpt":
        if yes("  Sign in with ChatGPT in your browser now?"):
            try:
                print("  Signed in as", sub.chatgpt_login() or "your account")
            except sub.ChatGPTAuthError as e:
                print("  " + str(e))
    else:
        exe = sub.find_claude()
        if exe and yes("  Run `claude auth login` now? (Claude Code opens its own browser sign-in)"):
            import subprocess
            subprocess.run([exe, "auth", "login"])
    ok, msg = connection_status(prov)
    if not ok:
        print("  " + msg)
    return ok


def _pick_chatgpt_model():
    try:
        models = sub.chatgpt_models()
    except Exception as e:
        print(f"  Could not list your models: {e}")
        return ask("  Type a model slug to try anyway (it will be proven by the test call)", "")
    if not models:
        print("  Your account returned no listed models.")
        return ask("  Type a model slug to try anyway", "")
    for i, (slug, name) in enumerate(models, 1):
        print(f"  {i}. {slug}  ({name})")
    pick = ask("  Choose a model number (or type a slug)", "1")
    return models[int(pick) - 1][0] if pick.isdigit() and 1 <= int(pick) <= len(models) else pick


def choose_role(role, default_spec, ollama_url):
    label = LABEL[role]
    d_prov, d_model = parse_spec(default_spec)
    names = list(PROVIDER_NAMES)
    print(f"\n--- {label} ---")
    for i, n in enumerate(names, 1):
        print(f"  {i}. {PROVIDER_NAMES[n]}")
    while True:
        pick = ask(f"{label} provider (1-{len(names)})", str(names.index(d_prov) + 1) if d_prov in names else "1")
        if pick.isdigit() and 1 <= int(pick) <= len(names):
            prov = names[int(pick) - 1]
            break
        print(f"  Please enter a number from 1 to {len(names)}.")
    default_model = d_model if prov == d_prov else SUGGEST[prov]
    if prov == "chatgpt":
        if not _ensure_connection(prov):
            sys.exit(f"{label}: the ChatGPT connection is not ready. Nothing was substituted.")
        return f"chatgpt:{_pick_chatgpt_model()}"
    if prov == "claudecode":
        if not _ensure_connection(prov):
            sys.exit(f"{label}: Claude Code is not ready. Nothing was substituted.")
        print("  Claude Code has no model-list command; use an alias (sonnet, opus, haiku, ...), a full model name, "
              "or 'default' for your account's default. The test call reports which model actually answered.")
        return f"claudecode:{ask(f'{label} model', default_model)}"
    if prov == "ollama":
        installed = ollama_models(ollama_url)
        if installed is None:
            print(f"  Cannot reach Ollama at {ollama_url}. Install/start it, or pick another provider "
                  "(you can still type a model name).")
        elif installed:
            print("  Pulled Ollama models: " + ", ".join(installed))
        else:
            print("  Ollama is running but no models are pulled (ollama pull <name>).")
    else:
        print(f"  Type any model ID your {PROVIDER_NAMES[prov]} can call "
              f"(example only, not verified: {SUGGEST[prov]}).")
    model = ask(f"{label} model ID", default_model)
    return f"{prov}:{model}"


def collect_keys(specs):
    """Masked key entry for hosted roles, sharing a key across roles when the user agrees."""
    keys, sources = {}, {}
    for role, label in ROLES:
        prov = provider_of(specs[role])
        if prov in ("ollama", "mock"):
            keys[role], sources[role] = None, "not needed (local)"
            continue
        if prov in CONNECTIONS:
            keys[role], sources[role] = None, CONNECTION_SOURCE[prov]
            continue
        if os.environ.get(ROLE_KEY_ENV[role]):
            keys[role], sources[role] = os.environ[ROLE_KEY_ENV[role]], f"environment variable {ROLE_KEY_ENV[role]}"
            print(f"{label}: using {ROLE_KEY_ENV[role]} from the environment.")
            continue
        prior = next((r for r, _ in ROLES if r in keys and keys[r] and provider_of(specs[r]) == prov), None)
        if prior and yes(f"{label}: reuse the {PROVIDER_NAMES[prov]} key already entered for {LABEL[prior]}?"):
            keys[role], sources[role] = keys[prior], sources[prior]
            continue
        name = env_var_name(prov)
        if name and yes(f"{label}: use {name} from the environment?"):
            keys[role], sources[role] = env_key(prov), f"environment variable {name}"
            continue
        while True:
            k = read_secret(f"{label}: paste your {PROVIDER_NAMES[prov]} API key (hidden, kept only for this session): ")
            if k:
                keys[role], sources[role] = k, "entered this session"
                break
            if not yes("  Nothing entered. Try again?"):
                sys.exit(f"{label} cannot run without a {PROVIDER_NAMES[prov]} key.")
    return keys, sources


def wizard(defaults, ollama_url):
    """Returns (specs, keys, sources, ollama_url, save_name). Nothing here touches the disk."""
    print("AIE demo setup: choose a provider and model for each role. Press Enter to accept [defaults].")
    if not yes(f"Ollama address is {ollama_url}. Keep it?"):
        ollama_url = ask("Ollama address", ollama_url)
    specs = {role: choose_role(role, defaults[role], ollama_url) for role, _ in ROLES}
    problems = validate_specs(specs)
    if problems:
        sys.exit("\n".join(problems))
    keys, sources = collect_keys(specs)
    print("\nYour setup")
    for role, label in ROLES:
        print(f"  {label:8} {specs[role]:44} key: {sources[role]}")
    if overlaps(specs):
        print("  NOTE: the Judge is also " + " and ".join(LABEL[r] for r in overlaps(specs)) +
              ". It may favour its own output; this will be recorded and shown on replay.")
    if yes("Test each model with one tiny real call before the full run?"):
        results = smoke(specs, keys, ollama_url)
        for _, ok, msg in results:
            print(f"  [{'ok' if ok else 'FAILED'}] {msg}")
        if not all(ok for _, ok, _ in results):
            sys.exit("Fix the failed role(s) and start again. Nothing was substituted and nothing was run.")
    if not yes("Run the six-prompt comparison now?"):
        sys.exit("Stopped before running. Nothing was saved.")
    save = ask("Save as aie/saved/<name> for later replay (blank = runs/aie_<timestamp>)", "")
    return specs, keys, sources, ollama_url, save
