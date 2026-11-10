"""Tests for the ChatGPT-subscription and Claude Code connections.

These use LOCAL STUBS (a localhost HTTP server and a fake `claude` program). They test this program's request
building, parsing, isolation, and error mapping. They do NOT show that OpenAI or Anthropic accept the requests:
that needs a real sign-in (see TA_DEMO.md, "What was actually verified").
Run: python -m unittest discover -s tests
"""
import json, os, stat, sys, tempfile, threading, time, unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import model_clients, subscription_clients as sc  # noqa: E402


def sse(*events):
    return "".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in events).encode()


class ChatGPT(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["AIE_CREDENTIALS_DIR"] = self.tmp.name
        self.seen = {}
        outer = self

        class H(BaseHTTPRequestHandler):
            def _send(self, code, body, ctype="application/json"):
                self.send_response(code); self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)

            def do_GET(self):
                outer.seen["models_auth"] = self.headers.get("Authorization")
                self._send(200, json.dumps({"models": [{"slug": "m-1", "display_name": "M One", "visibility": "list"},
                                                       {"slug": "hidden", "visibility": "hide"}]}).encode())

            def do_POST(self):
                outer.seen["auth"] = self.headers.get("Authorization")
                outer.seen["body"] = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                mode = outer.mode
                if mode == "ok":
                    self._send(200, sse({"type": "response.output_text.delta", "delta": "Hel"},
                                        {"type": "response.output_text.delta", "delta": "lo"},
                                        {"type": "response.completed", "response": {"model": "m-1-actual"}}), "text/event-stream")
                elif mode == "failed":
                    self._send(200, sse({"type": "response.failed",
                                         "response": {"error": {"code": "subscription_sharing_usage_limit_exceeded"}}}), "text/event-stream")
                elif mode == "cut":
                    self._send(200, sse({"type": "response.output_text.delta", "delta": "partial"}), "text/event-stream")
                elif mode == "403":
                    self._send(403, json.dumps({"error": {"code": "subscription_sharing_user_not_eligible"}}).encode())

            def log_message(self, *a):
                pass

        self.srv = HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.old_base, sc.API_BASE = sc.API_BASE, f"http://127.0.0.1:{self.srv.server_port}/v1"
        self.mode = "ok"

    def tearDown(self):
        sc.API_BASE = self.old_base
        self.srv.shutdown()
        os.environ.pop("AIE_CREDENTIALS_DIR", None)
        self.tmp.cleanup()

    def sign_in_record(self):
        sc._write_private(sc._auth_file(), {"client_id": "oaiapp_test", "email": "t@example.com", "access_token": "tok-access-0123456789",
                                            "refresh_token": "tok-refresh-0123456789", "scope": sc.SCOPES, "expires_at": time.time() + 3600})

    def test_not_signed_in_message_and_no_fallback(self):
        r = model_clients.chat("chatgpt:m-1", "s", "u")
        self.assertEqual(r.status, "api_error")
        self.assertIn("connect chatgpt", r.detail)
        self.assertNotIn("seen_body", self.seen)          # nothing was sent anywhere

    def test_success_request_shape_and_reported_model(self):
        self.sign_in_record()
        r = model_clients.chat("chatgpt:m-1", "SYSTEM TEXT", "USER TEXT", temperature=0.2, max_tokens=50, seed=1,
                               json_schema={"type": "object"})
        self.assertEqual((r.status, r.text, r.meta["model_reported"]), ("ok", "Hello", "m-1-actual"))
        b = self.seen["body"]
        self.assertEqual(self.seen["auth"], "Bearer tok-access-0123456789")
        self.assertEqual((b["model"], b["instructions"], b["store"], b["stream"]), ("m-1", "SYSTEM TEXT", False, True))
        self.assertEqual(b["input"], [{"role": "user", "content": "USER TEXT"}])
        for unsupported in ("temperature", "max_output_tokens", "seed", "text", "metadata", "user"):
            self.assertNotIn(unsupported, b)

    def test_models_listing_hides_unlisted(self):
        self.sign_in_record()
        self.assertEqual(sc.chatgpt_models(), [("m-1", "M One")])

    def test_usage_limit_and_ineligible_are_visible_errors(self):
        self.sign_in_record()
        self.mode = "failed"
        r = model_clients.chat("chatgpt:m-1", "s", "u")
        self.assertEqual(r.status, "api_error"); self.assertIn("exhausted", r.detail); self.assertIn("API billing", r.detail)
        self.mode = "403"
        r = model_clients.chat("chatgpt:m-1", "s", "u")
        self.assertEqual(r.status, "api_error"); self.assertIn("not eligible", r.detail)

    def test_truncated_stream_is_not_a_response(self):
        self.sign_in_record()
        self.mode = "cut"
        r = model_clients.chat("chatgpt:m-1", "s", "u")
        self.assertEqual((r.status, r.text), ("api_error", ""))

    def test_missing_plan_scope_refused(self):
        sc._write_private(sc._auth_file(), {"client_id": "x", "access_token": "a", "refresh_token": "b", "scope": "openid", "expires_at": time.time() + 3600})
        self.assertFalse(sc.chatgpt_status()[0])

    def test_tokens_scrubbed_and_stored_outside_repo(self):
        self.sign_in_record()
        sc._load_auth()
        self.assertEqual(model_clients.scrub("oops tok-access-0123456789 end"), "oops *** end")
        self.assertNotIn(ROOT, sc.cred_dir().resolve().parents)
        os.environ["AIE_CREDENTIALS_DIR"] = str(ROOT / "aie" / "creds")
        with self.assertRaises(RuntimeError):
            sc.cred_dir()


class ClaudeCode(unittest.TestCase):
    FAKE = '''import json, os, sys
a = sys.argv[1:]
if a[:2] == ["auth", "status"]:
    print(json.dumps({"loggedIn": os.environ.get("FAKE_AUTH", "claude.ai") != "none", "authMethod": os.environ.get("FAKE_AUTH", "claude.ai"), "subscriptionType": "pro"})); sys.exit(0)
if a == ["--version"]:
    print("9.9.9 (Claude Code)"); sys.exit(0)
prompt = sys.stdin.read()
json.dump({"argv": a, "cwd": os.getcwd(), "prompt": prompt, "api_key_visible": "ANTHROPIC_API_KEY" in os.environ,
           "system": open(a[a.index("--system-prompt-file") + 1], encoding="utf-8").read()}, open(os.environ["FAKE_LOG"], "w"))
mode = os.environ.get("FAKE_MODE", "ok")
if mode == "ok":
    print(json.dumps({"is_error": False, "result": "fine answer", "stop_reason": "end_turn", "num_turns": 1, "modelUsage": {"claude-test-model": {}}}))
elif mode == "limit":
    print(json.dumps({"is_error": True, "result": "You've hit your session limit \\u00b7 resets 3:45pm", "modelUsage": {}})); sys.exit(1)
elif mode == "expired":
    print(json.dumps({"is_error": True, "result": "Failed to authenticate: OAuth session expired and could not be refreshed", "modelUsage": {}})); sys.exit(1)
'''

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        (d / "fake_claude.py").write_text(self.FAKE, encoding="utf-8")
        if os.name == "nt":
            (d / "claude.bat").write_text(f'@"{sys.executable}" "{d / "fake_claude.py"}" %*\n')
        else:
            f = d / "claude"
            f.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{d / "fake_claude.py"}" "$@"\n')
            f.chmod(f.stat().st_mode | stat.S_IEXEC)
        self.env = {k: os.environ.get(k) for k in ("PATH", "FAKE_LOG", "FAKE_MODE", "FAKE_AUTH", "ANTHROPIC_API_KEY")}
        os.environ["PATH"] = str(d) + os.pathsep + os.environ["PATH"]
        os.environ["FAKE_LOG"] = str(d / "log.json")
        os.environ["ANTHROPIC_API_KEY"] = "sk-ant-should-not-be-used"
        os.environ.pop("FAKE_MODE", None); os.environ.pop("FAKE_AUTH", None)
        sc._status_cache.clear()

    def tearDown(self):
        for k, v in self.env.items():
            if v is None: os.environ.pop(k, None)
            else: os.environ[k] = v
        sc._status_cache.clear()
        self.tmp.cleanup()

    def log(self):
        return json.loads(Path(os.environ["FAKE_LOG"]).read_text(encoding="utf-8"))

    def test_success_isolation_and_metadata(self):
        r = model_clients.chat("claudecode:sonnet", "SYS PROMPT", "judge this: <x> & | ^ \"quoted\"")
        self.assertEqual((r.status, r.text), ("ok", "fine answer"))
        self.assertEqual(r.meta["models_reported"], ["claude-test-model"])
        self.assertIn("agent harness", r.meta["harness_note"])
        self.assertIn("ANTHROPIC_API_KEY", r.meta["ignored_env_vars"])
        lg = self.log()
        a = lg["argv"]
        for flag in ("-p", "--safe-mode", "--no-session-persistence"):
            self.assertIn(flag, a)
        self.assertEqual(a[a.index("--tools") + 1], "")                 # all tools off
        self.assertEqual(a[a.index("--max-turns") + 1], "1")
        self.assertEqual(a[a.index("--model") + 1], "sonnet")
        self.assertNotIn("--bare", a)                                    # --bare would ignore the subscription login
        self.assertFalse(lg["api_key_visible"])                          # API-key variable removed from the CLI's env
        self.assertEqual(lg["prompt"], "judge this: <x> & | ^ \"quoted\"")
        self.assertEqual(lg["system"], "SYS PROMPT")
        self.assertNotIn(str(ROOT), Path(lg["cwd"]).resolve().parents.__str__() + lg["cwd"])   # not run inside the repo

    def test_default_model_omits_flag(self):
        model_clients.chat("claudecode:default", "s", "u")
        self.assertNotIn("--model", self.log()["argv"])

    def test_limit_and_expired_messages_do_not_fall_back(self):
        os.environ["FAKE_MODE"] = "limit"
        r = model_clients.chat("claudecode:sonnet", "s", "u")
        self.assertEqual(r.status, "api_error"); self.assertIn("limit", r.detail); self.assertIn("API billing", r.detail)
        os.environ["FAKE_MODE"] = "expired"
        r = model_clients.chat("claudecode:sonnet", "s", "u")
        self.assertEqual(r.status, "api_error"); self.assertIn("claude auth login", r.detail)

    def test_non_subscription_login_refused(self):
        os.environ["FAKE_AUTH"] = "api_key"
        r = model_clients.chat("claudecode:sonnet", "s", "u")
        self.assertEqual(r.status, "api_error"); self.assertIn("not a Claude subscription", r.detail)
        self.assertFalse(Path(os.environ["FAKE_LOG"]).exists())          # the CLI was never asked to generate

    def test_not_logged_in_refused(self):
        os.environ["FAKE_AUTH"] = "none"
        r = model_clients.chat("claudecode:sonnet", "s", "u")
        self.assertEqual(r.status, "api_error"); self.assertIn("not logged in", r.detail)


if __name__ == "__main__":
    unittest.main()
