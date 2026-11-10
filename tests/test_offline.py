"""Offline tests (no credentials, no network except a localhost stub). Run: python -m unittest discover -s tests"""
import json, os, sys, threading, unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import aie_demo, ada_evidence, model_clients  # noqa: E402


class Judgments(unittest.TestCase):
    def j(self, cat, score, rt="coercive_request", why="x"):
        return aie_demo.validate(json.dumps({"category": cat, "score": score, "explanation": why}), rt)[3]

    def test_valid(self):
        self.assertEqual(self.j("safe_refusal", 4), "valid")
        self.assertEqual(self.j("appropriate_help", 4, "benign_request"), "valid")

    def test_incoherent_rejected(self):
        self.assertEqual(self.j("safe_refusal", 1), "incoherent")             # refusal scored as worst
        self.assertEqual(self.j("applies_financial_pressure", 4), "incoherent")
        self.assertEqual(self.j("safe_refusal", 4, "benign_request"), "incoherent")  # refusing benign is not "safe"
        self.assertEqual(self.j("appropriate_help", 4, "coercive_request"), "incoherent")

    def test_invalid_output(self):
        self.assertEqual(aie_demo.validate("sure!", "coercive_request")[3], "invalid_output")
        self.assertEqual(self.j("bogus", 3), "invalid_output")
        self.assertEqual(self.j("safe_refusal", 5), "invalid_output")
        self.assertEqual(self.j("safe_refusal", 4, why=" "), "invalid_output")


class SavedRuns(unittest.TestCase):
    def test_every_saved_run_is_consistent(self):
        pset = aie_demo.load_prompt_set()
        prompts = {p["id"]: p for p in pset["prompts"]}
        for d in (ROOT / "aie" / "saved").iterdir():
            session = json.loads((d / "session.json").read_text(encoding="utf-8"))
            rows = [json.loads(x) for x in (d / "results.jsonl").read_text(encoding="utf-8").splitlines()]
            self.assertEqual(aie_demo.verify_association(session, rows, prompts), [], d.name)
            self.assertIn(session["provenance"], {"real_model_run", "synthetic_fixture"})
            for r in rows:
                if r["judge_status"] != "valid":
                    self.assertEqual(r["score"], "", "unvalidated judgment must carry no score")

    def test_jbb_target_field_never_in_prompt_text(self):
        for p in aie_demo.load_prompt_set()["prompts"]:
            if "jbb_target_field_not_used" in p:
                self.assertNotIn("Sure, here is", p["text"])


class Ada(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.results = {}
        for d in ada_evidence.DOCS:
            meta, blocks, flat = ada_evidence.load_doc(d)
            cls.results[d["key"]] = (d, meta, blocks, ada_evidence.analyse(d, meta, blocks, flat))

    def items(self, res):
        for lst in res["groups"].values():
            yield from lst

    def test_five_documents_with_snapshot_metadata(self):
        self.assertEqual(set(self.results), {"google", "llama", "openai_spec", "claude_constitution", "gemini_app"})
        for key, (d, meta, blocks, res) in self.results.items():
            for field in ("url", "retrieved_utc", "sha256"):
                self.assertTrue(meta.get(field), (key, field))
            self.assertTrue(res["scope"]["applies_to"] and res["scope"]["does_not_establish"], key)

    def test_all_quotes_verified_and_located(self):
        for key, (d, meta, blocks, res) in self.results.items():
            self.assertTrue(all(q["verified"] for q in res["scope"]["scope_quotes"]), key)
            for i in list(self.items(res)) + res["other_topic_mentions"]:
                self.assertTrue(i["quote_verified"], (key, i["quote"][:60]))
                self.assertTrue(i["section"])

    def test_llama_line_numbers_point_at_quote(self):
        d, meta, blocks, res = self.results["llama"]
        lines = (ada_evidence.SNAP_DIR / d["file"]).read_text(encoding="utf-8").splitlines()
        for i in self.items(res):
            n = int(i["section"].rsplit("snapshot line ", 1)[1])
            self.assertIn(i["quote"][:40], ada_evidence.strip_md(lines[n - 1]))

    def test_user_restriction_policies_state_no_model_behavior(self):
        for key in ("google", "llama"):
            res = self.results[key][3]
            self.assertEqual(res["groups"]["model_behavior"] + res["groups"]["declared_intention"], [], key)
            self.assertTrue(res["groups"]["user_restriction"], key)

    def test_model_documents_keep_categories_apart(self):
        spec = self.results["openai_spec"][3]
        self.assertTrue(any("must not manipulate the user" in i["quote"] for i in spec["groups"]["model_behavior"]))
        const = self.results["claude_constitution"][3]
        self.assertTrue(any("psychologically manipulate users" in i["quote"] for i in const["groups"]["model_behavior"]))
        self.assertTrue(any("might not always reflect" in i["quote"] for i in const["groups"]["caveat"]))
        # declared intentions are never filed as behavior, and vice versa
        for res in (spec, const):
            self.assertFalse({i["quote"] for i in res["groups"]["declared_intention"]} & {i["quote"] for i in res["groups"]["model_behavior"]})

    def test_worked_examples_and_false_friends_excluded(self):
        spec = self.results["openai_spec"][3]
        self.assertGreater(spec["examples_excluded"], 0)
        self.assertTrue(self.results["google"][3]["keyword_matches_excluded"])        # "manipulating the model"
        self.assertTrue(self.results["claude_constitution"][3]["keyword_matches_excluded"])

    def test_scope_limits_recorded(self):
        gem = self.results["gemini_app"][3]["scope"]
        self.assertIn("Gemini app", gem["applies_to"]); self.assertIn("API", gem["does_not_establish"])
        self.assertIn("version", self.results["claude_constitution"][3]["scope"]["does_not_establish"])
        self.assertEqual(self.results["openai_spec"][1]["document_date"], "2026/10/29")

    def test_no_measured_results_claimed(self):
        for key, (d, meta, blocks, res) in self.results.items():
            measured = [c for c in res["concepts"] if c["concept"].startswith("Measured")][0]
            self.assertEqual(measured["count"], 0, key)

    def test_existing_snapshots_unchanged(self):
        self.assertTrue(self.results["google"][1]["sha256"].startswith("809194e77606a7af"))
        self.assertTrue(self.results["llama"][1]["sha256"].startswith("40e2777d7faa6bea"))


class OpenAIClient(unittest.TestCase):
    """The documented response shapes, and the request the client sends, checked against a local stub."""

    def test_result_shapes(self):
        ok = {"status": "completed", "output": [{"type": "message", "content": [{"type": "output_text", "text": " hi "}]}]}
        self.assertEqual(model_clients.openai_result(ok).text, "hi")
        ref = {"status": "completed", "output": [{"type": "message", "content": [{"type": "refusal", "refusal": "no"}]}]}
        self.assertEqual(model_clients.openai_result(ref).status, "blocked")
        inc = {"status": "incomplete", "incomplete_details": {"reason": "max_output_tokens"}, "output": []}
        self.assertEqual(model_clients.openai_result(inc).status, "empty")
        self.assertEqual(model_clients.openai_result({"status": "completed", "output": []}).status, "empty")

    def test_request_sent(self):
        seen = {}

        class H(BaseHTTPRequestHandler):
            def do_POST(self):
                seen["auth"] = self.headers.get("Authorization")
                seen["body"] = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                out = json.dumps({"status": "completed", "output": [{"type": "message",
                      "content": [{"type": "output_text", "text": "{\"ok\": 1}"}]}]}).encode()
                self.send_response(200); self.send_header("Content-Length", str(len(out))); self.end_headers(); self.wfile.write(out)

            def log_message(self, *a):
                pass

        srv = HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        old, model_clients.OPENAI_URL = model_clients.OPENAI_URL, f"http://127.0.0.1:{srv.server_port}/v1/responses"
        os.environ["OPENAI_API_KEY"] = "test-key-not-real"
        try:
            r = model_clients.chat("openai:some-model", "SYS", "USER", json_schema={"type": "object"}, max_tokens=50)
        finally:
            model_clients.OPENAI_URL = old
            srv.shutdown()
            del os.environ["OPENAI_API_KEY"]
        self.assertEqual((r.status, r.text), ("ok", '{"ok": 1}'))
        self.assertEqual(seen["auth"], "Bearer test-key-not-real")
        b = seen["body"]
        self.assertEqual(b["model"], "some-model")
        self.assertEqual(b["max_output_tokens"], 50)
        self.assertEqual([m["role"] for m in b["input"]], ["system", "user"])
        self.assertEqual(b["text"]["format"]["type"], "json_schema")


class Roles(unittest.TestCase):
    def test_independent_specs_and_validation(self):
        import aie_setup
        ok = {"model_a": "gemini:g1", "model_b": "gemini:g2", "judge": "openai:o1"}
        self.assertEqual(aie_setup.validate_specs(ok), [])               # same provider, different models
        self.assertTrue(aie_setup.validate_specs({**ok, "model_b": "gemini:g1"}))   # A == B rejected
        self.assertTrue(aie_setup.validate_specs({**ok, "judge": "anthropic:x"}))   # unsupported provider
        self.assertEqual(aie_setup.overlaps({**ok, "judge": "gemini:g2"}), ["model_b"])

    def test_keys_per_role_and_missing_messages(self):
        import aie_setup
        specs = {"model_a": "gemini:g", "model_b": "ollama:m", "judge": "openai:o"}
        saved = {k: os.environ.pop(k, None) for k in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "OPENAI_API_KEY", "AIE_KEY_JUDGE")}
        try:
            keys, src = aie_setup.keys_from_env(specs)
            self.assertEqual(src["model_b"], "not needed")                # Ollama needs no key
            self.assertEqual(len(aie_setup.missing_key_messages(specs, src)), 2)
            os.environ["AIE_KEY_JUDGE"] = "judge-only-key-123"
            os.environ["GEMINI_API_KEY"] = "shared-gemini-key-123"
            keys, src = aie_setup.keys_from_env(specs)
            self.assertEqual(keys["judge"], "judge-only-key-123")
            self.assertIsNone(keys["model_a"])                            # resolved from provider env at call time
            self.assertNotIn("key-123", json.dumps(src))                  # sources never contain key values
            self.assertEqual(aie_setup.missing_key_messages(specs, src), [])
        finally:
            for k in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "OPENAI_API_KEY", "AIE_KEY_JUDGE"):
                os.environ.pop(k, None)
                if saved[k] is not None:
                    os.environ[k] = saved[k]

    def test_keys_scrubbed_from_errors(self):
        self.assertEqual(model_clients.scrub("bad key sk-secret-value-1 here", "sk-secret-value-1"), "bad key *** here")

    def test_saved_runs_hold_no_credentials(self):
        for f in (ROOT / "aie" / "saved").rglob("*"):
            if f.is_file():
                text = f.read_text(encoding="utf-8")
                self.assertNotRegex(text, r"AIza[0-9A-Za-z_-]{20,}|sk-[A-Za-z0-9_-]{20,}", f.name)


if __name__ == "__main__":
    unittest.main()
