"""ADA demo: documentary evidence about coercion, manipulation, threats, and user autonomy.

Five official documents are kept as local snapshots (ada/snapshots/): Google's Generative AI Prohibited Use
Policy, Meta's Llama 3.2 Acceptable Use Policy, the OpenAI Model Spec, Claude's Constitution, and the Gemini app
policy guidelines. This script reads ONLY those snapshots (no network, no credentials, no model):

  python scripts/ada_evidence.py run        # find evidence, verify quotes, write ada/output/
  python scripts/ada_evidence.py snapshot   # fetch snapshots that are missing (--refresh re-downloads; needs internet)

Method (deliberately simple and deterministic; classification is by wording and is a heuristic to review):
  1. Split each snapshot into blocks (paragraphs / list items), each with a section reference.
  2. Keyword rules tag blocks about coercion/threats, manipulation, deception, and user autonomy.
  3. Each tagged sentence is placed in ONE category, keeping apart:
       user_restriction      a restriction imposed on people who use the service
       model_behavior        a statement of intended model behavior, phrased as an instruction to / about the model
       declared_intention    what the provider says it wants or aims for
       safeguard_description text describing safeguards or evaluations (a description, not a result)
       caveat                the provider saying intentions may not match actual behavior
  4. Concepts with no matching text are reported as not found IN THIS CORPUS (not in the world).
  5. Every quotation is re-checked against an independent text view of its snapshot before it is printed.
  6. Worked examples (the Model Spec's good/bad sample conversations) are excluded: they illustrate, they do not state policy.

Documents are untrusted reference content: they are only searched and quoted, never obeyed.
"""

import argparse
import hashlib
import html
import json
import re
import sys
import urllib.request
from datetime import datetime, timezone
from html.parser import HTMLParser

from repo_utils import ROOT

SNAP_DIR = ROOT / "ada" / "snapshots"
OUT_DIR = ROOT / "ada" / "output"

DOCS = [
    {"key": "google", "title": "Google Generative AI Prohibited Use Policy",
     "url": "https://policies.google.com/terms/generative-ai/use-policy",
     "file": "google_genai_use_policy.html", "kind": "html"},
    {"key": "llama", "title": "Llama 3.2 Acceptable Use Policy (meta-llama/llama-models)",
     "url": "https://github.com/meta-llama/llama-models/blob/main/models/llama3_2/USE_POLICY.md",
     "fetch_url": "https://raw.githubusercontent.com/meta-llama/llama-models/main/models/llama3_2/USE_POLICY.md",
     "file": "llama_3_2_use_policy.md", "kind": "md"},
    {"key": "openai_spec", "title": "OpenAI Model Spec",
     "url": "https://model-spec.openai.com/",
     "fetch_url": "https://model-spec.openai.com/2026-10-29.html",
     "file": "openai_model_spec_2026-10-29.html", "kind": "web"},
    {"key": "claude_constitution", "title": "Claude's Constitution (Anthropic)",
     "url": "https://www.anthropic.com/constitution",
     "file": "claude_constitution.html", "kind": "web"},
    {"key": "gemini_app", "title": "Gemini app safety and policy guidelines",
     "url": "https://gemini.google/policy-guidelines/",
     "file": "gemini_app_policy_guidelines.html", "kind": "web"},
]

# ---------- scope and applicability (recorded per document; quotes are re-verified at run time) ----------
SCOPE = {
    "google": {
        "publisher": "Google", "document_type": "usage policy", "voice": "users",
        "applies_to": "People using generative AI in Google products and services that refer to this policy.",
        "does_not_establish": "How any Google model behaves; it restricts users and does not describe model behavior. "
                              "It is not the Gemini app guidelines and says nothing specific about the Gemini API model.",
        "scope_quotes": ["The following restrictions apply to your interactions with generative AI in the Google products and services that refer to this policy."],
    },
    "llama": {
        "publisher": "Meta", "document_type": "acceptable use policy", "voice": "users",
        "applies_to": "People who access or use Llama 3.2 (the policy says use of the model implies agreement to it).",
        "does_not_establish": "How Llama 3.2 behaves, or whether any safeguard exists; it is a set of use restrictions "
                              "specific to Llama 3.2 and does not cover other Llama versions or Meta products.",
        "scope_quotes": ["If you access or use Llama 3.2, you agree to this Acceptable Use Policy"],
    },
    "openai_spec": {
        "publisher": "OpenAI", "document_type": "model behavior specification (intended behavior)", "voice": "model",
        "applies_to": "Intended behavior of OpenAI's GPT models in its products and API platform, as of the dated version "
                      "snapshotted (2026/10/29). The root URL redirects to the current dated page; a later version may differ.",
        "does_not_establish": "How any specific model version actually behaves. It states intended behavior; a newer or "
                              "broader spec does not show that an older or different model follows it.",
        "scope_quotes": ["The Model Spec outlines the intended behavior for"],
    },
    "claude_constitution": {
        "publisher": "Anthropic", "document_type": "statement of intended values and behavior", "voice": "model",
        "applies_to": "Anthropic's mainline, general-access Claude models; the page says some specialized models do not fully fit it.",
        "does_not_establish": "How a particular Claude model or version behaves, or how Claude behaves as an evaluator or "
                              "inside an agent harness such as Claude Code. The page itself says Claude's behavior may not "
                              "always reflect the constitution. No version or date is stated on the page.",
        "scope_quotes": ["This constitution is written for our mainline, general-access Claude models.",
                         "behavior might not always reflect the constitution"],
    },
    "gemini_app": {
        "publisher": "Google", "document_type": "product policy guidelines", "voice": "model",
        "applies_to": "The Gemini app (the consumer product).",
        "does_not_establish": "How the Gemini API model behaves: the guidelines are for the app and are not automatically "
                              "attributable to API use or to a particular model version. No version or date is stated on the page.",
        "scope_quotes": ["Our goal for the Gemini app is to be maximally helpful to users"],
    },
}

# ---------- rules ----------
TOPICS = {
    "coercion/threats": re.compile(r"coerc|threat|intimidat|blackmail|extort|bully|bullying|harass|compel|undue influence"
                                   r"|pressur(?:e|es|ed|ing)\s+(?:the |a |an )?(?:user|users|person|people|them|him|her|someone)|pressuring|high-pressure", re.I),
    "manipulation": re.compile(r"manipulat|dark pattern|exploit\w* (?:psycholog|emotion|cognitive|weakness|vulnerab)|persuasi|sycophan|flatter", re.I),
    "deception": re.compile(r"deceiv|decepti|mislead|fraud|scam|impersonat|gaslight", re.I),
    # "autonomy" about people. "autonomous(ly)" and "scope of autonomy" describe an AI agent acting on its own, not user autonomy.
    "user autonomy": re.compile(r"(?<!scope of )\bautonomy\b|self-determination"
                                r"|own (?:decisions?|choices?|conclusions?|reasoning)|right to (?:make|decide|reach|choose)"
                                r"|human agency|user control|free(?:ly)? (?:choose|decide)|informed (?:decision|choice)"
                                r"|independent (?:decision|thinking|judg|reasoning)|epistemic|nudg", re.I),
}
TOPIC_WEIGHT = {"coercion/threats": 3, "manipulation": 3, "user autonomy": 3, "deception": 1}
# Physical/security "threats" and similar are not coercion; these phrases are removed before tagging.
THREAT_NOISE = re.compile(r"imminent threat|threats? (?:to|of) (?:public|physical|life|safety|national|security|infrastructure|human|harm|violence|death|bodily|the)"
                          r"|(?:security|existential|physical|serious|credible) threats?|fundamentally threatening|threatening to (?:human|the|global)", re.I)
# "manipulating the model" is about people attacking the model, not the model manipulating people.
FALSE_FRIEND = re.compile(r"manipulat\w*\s+(?:the model|the assistant|claude|gemini|gpt|chatgpt|it\b)|manipulation of (?:the model|claude|gemini|gpt)"
                          r"|manipulate (?:the )?model|jailbreak", re.I)
USER_SUBJECT = re.compile(r"^(?:users?|you|anyone|people who use)\b[^.]{0,40}\b(?:should|must|may not|agree|abide|expected? to)\b|\bwe expect users\b", re.I)
USER_PROHIBITION = re.compile(r"\bdo not\b|\byou agree you will not\b|\bprohibited\b|\bnot use\b", re.I)
MODEL_SUBJECT = re.compile(r"\b(?:the assistant|assistant|gpt|chatgpt|claude|gemini|the model|models?)\b", re.I)
PRONOUN_SUBJECT = re.compile(r"^(?:it|they)\b", re.I)
MODAL = re.compile(r"\b(?:should(?:n['’]t| not)?|must(?:n['’]t| not)?|shall|never|will not|won['’]t|cannot|can['’]t|avoids?|refrains?"
                   r"|do(?:es)? not|don['’]t|doesn['’]t|aims? to|tries to|is designed to|relies? (?:only )?on)\b", re.I)
IMPERATIVE = re.compile(r"^(?:do not|don['’]t|never|avoid)\b", re.I)
INTENTION = re.compile(r"\b(?:we|anthropic|openai|google)\b[^.]{0,40}\b(?:want|hope|believe|aim|intend|strive|seek|are committed|is committed|commit)\b"
                       r"|\bour (?:goal|intention|aim|hope|vision)\b|\bis committed to\b", re.I)
SAFEGUARD = re.compile(r"safeguard|mitigat|red[- ]?team|classifier|\bevaluations?\b|\bevaluat(?:e|ed|es|ing) (?:the )?(?:model|claude|gpt|gemini|outputs?|performance)"
                       r"|system card|\bwe (?:train|test|measure|monitor)\b|\bmonitor|\baudit|safety (?:measures|filters|systems)", re.I)
CAVEAT = re.compile(r"might not always|may not always|not always reflect|does not (?:always )?reflect|can make mistakes"
                    r"|comes? apart from|fall short|may sometimes produce|imperfect training|reflect the limits", re.I)
CAVEAT_ABOUT = re.compile(r"behavio|output|reflect|violat|guideline|intention", re.I)
MEASURED = re.compile(r"\d+(?:\.\d+)?\s?%|\bpercent\b|\bbenchmark|evaluation results", re.I)
CATEGORIES = [("model_behavior", "Statements of intended model behavior (instructions to / about the model)"),
              ("declared_intention", "Declared intentions (what the provider says it wants or aims for)"),
              ("user_restriction", "Restrictions imposed on users"),
              ("safeguard_description", "Documentary descriptions of safeguards or evaluations (descriptions, not results)"),
              ("caveat", "Provider caveats: intended behavior may differ from actual behavior")]
TOP_N = 5

INTERPRETATION = (
    "Read each category for what it is. A restriction on users says what users may not do. A statement of intended model "
    "behavior or a declared intention says what the provider wants; it is not evidence that any model version does it. "
    "A description of safeguards says such measures exist or have limits; it supplies no results. None of this shows how a "
    "model actually behaves, which is what the AIE run observes, and a document that is silent is not evidence of absence "
    "beyond this corpus."
)


# ---------- snapshot extraction ----------
def norm_ws(s):
    return re.sub(r"\s+", " ", s).strip()


def norm(s):
    return re.sub(r"\s+", " ", s).strip()


class _Google(HTMLParser):
    """Collect <li> texts inside the policy body (div#main-content), with nesting ordinals."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.in_main = 0
        self.stack = []          # one entry per open <li>: {"ord": [...], "text": []}
        self.counters = [0]
        self.blocks = []
        self.intro = []
        self.title = ""
        self._tag_stack = []
        self._cur_h1 = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "div" and a.get("id") == "main-content":
            self.in_main = 1
        elif self.in_main and tag == "div":
            self.in_main += 1
        if not self.in_main:
            return
        if tag == "h1":
            self._cur_h1 = True
        if tag == "ol":
            self.counters.append(0)
        if tag == "li":
            self.counters[-1] += 1
            self.stack.append({"ord": [c for c in self.counters[1:]], "text": []})

    def handle_endtag(self, tag):
        if not self.in_main:
            return
        if tag == "h1":
            self._cur_h1 = False
        if tag == "li" and self.stack:
            li = self.stack.pop()
            self._emit(li)
        if tag == "ol":
            self.counters.pop()
        if tag == "div":
            self.in_main -= 1

    def _emit(self, li):
        text = norm("".join(li["text"]))
        if text:
            self.blocks.append({"ord": li["ord"], "text": text})

    def handle_data(self, data):
        if not self.in_main:
            return
        if self._cur_h1:
            self.title += data
        elif self.stack:
            self.stack[-1]["text"].append(data)   # text of the innermost <li> only
        else:
            self.intro.append(data)


def blocks_google(raw):
    p = _Google()
    p.feed(raw)
    blocks = []
    parents = {}
    for b in p.blocks:
        parents[tuple(b["ord"])] = b["text"]
    out = []
    for b in p.blocks:
        o = tuple(b["ord"])
        # The published page renders top-level items 1-4 and nested items a, b, c (checked in the rendered page).
        ref = f"item {o[0]}" + "".join(f"({chr(96 + n)})" for n in o[1:])
        parent = parents.get(o[:-1]) if len(o) > 1 else None
        out.append({"ref": ref, "parent": parent, "text": b["text"]})
    return out


def strip_md(s):
    s = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", s)
    return norm(s.replace("**", ""))


def blocks_llama(raw):
    """List items of the markdown with references that match what GitHub renders.

    Checked in the rendered page (2026-11-09): top-level items render as 1-5; the sub-list of item 1
    renders as roman numerals (i-viii) with a-f below; the lines under items 2 and 3 are NOT rendered as
    a list, they stay plain lines that keep the number printed in the source ("8." ... "19."). So the
    reference gives the top-level item, the sub-item position (with its rendered label for item 1) or the
    printed number (items 2-3), and the snapshot line number.
    """
    heading, out = "Preamble", []
    count = {}                          # depth -> running position within the current parent
    top, parents = 0, {}
    roman = ["i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x"]
    for n, line in enumerate(raw.replace("\r\n", "\n").split("\n"), start=1):
        m = re.match(r"^(\s*)(\d+)\.\s+(.*\S)\s*$", line)
        if not m:
            h = re.fullmatch(r"\*\*(.+?)\*\*", line.strip())
            if h and "Llama 3.2" not in h.group(1):
                heading, count, parents, top = strip_md(h.group(1)), {}, {}, 0
            elif line.strip() and not line.lstrip().startswith(("*", "-")):
                out.append({"ref": f"{heading} (paragraph), snapshot line {n}", "parent": None, "text": strip_md(line)})
            continue
        depth = len(m.group(1)) // 4
        if depth == 0:
            top, count = int(m.group(2)), {}
            ref = f"{heading}, item {top}"
        else:
            count[depth] = count.get(depth, 0) + 1
            for d in [d for d in count if d > depth]:
                del count[d]
            if top == 1 and depth == 1:
                ref = f"{heading}, item 1, sub-item {count[1]} (rendered '{roman[count[1] - 1]}')"
            elif top == 1 and depth == 2:
                ref = f"{heading}, item 1, sub-item {count[1]}, sub-sub-item {count[2]} (rendered '{chr(96 + count[2])}')"
            else:
                ref = f"{heading}, item {top}, line printed as '{m.group(2)}.'"
        ref += f", snapshot line {n}"
        text = strip_md(m.group(3))
        parents[depth] = text
        out.append({"ref": ref, "parent": parents.get(depth - 1) if depth else None, "text": text,
                    "restriction_on_users": heading == "Prohibited Uses"})
    return out


def flat_text(raw, kind):
    if kind == "html":
        body = raw[raw.find('id="main-content"'):]
        body = re.sub(r"<[^>]+>", " ", body)
        return norm(html.unescape(body))
    if kind == "web":
        import ada_web
        return ada_web.flat_text_web(raw)
    return norm(strip_md(raw))


def load_doc(doc):
    raw_path = SNAP_DIR / doc["file"]
    meta = json.loads((SNAP_DIR / (doc["file"] + ".meta.json")).read_text(encoding="utf-8"))
    raw_bytes = raw_path.read_bytes()
    if hashlib.sha256(raw_bytes).hexdigest() != meta["sha256"]:
        sys.exit(f"{raw_path} does not match its recorded sha256; refusing to use a modified snapshot.")
    raw = raw_bytes.decode("utf-8", errors="replace")
    if doc["kind"] == "web":
        import ada_web
        blocks = ada_web.blocks_web(raw)
    else:
        blocks = blocks_google(raw) if doc["kind"] == "html" else blocks_llama(raw)
    for b in blocks:
        b.setdefault("kind", "statement")
    return meta, blocks, flat_text(raw, doc["kind"])


# ---------- analysis ----------
def compact(x):
    return re.sub(r"\s+", "", x)


def verified(quote, flat):
    """Whitespace-insensitive, case-sensitive verbatim check against the independent text view."""
    return compact(quote) in compact(flat)


def sentences(text):
    return [t for t in re.split(r"(?<=[.!?])\s+(?=[A-Z\"'\u201c(])", text) if t.strip()]


def topic_tags(text):
    cleaned = THREAT_NOISE.sub(" ", text)
    return [name for name, rx in TOPICS.items() if rx.search(cleaned)]


def classify(sentence, block, voice):
    """One category per sentence. Returns (category, why). Heuristic: wording only."""
    restriction = block.get("restriction_on_users") or (voice == "users" and USER_PROHIBITION.search(sentence + " " + (block.get("parent") or "")))
    if restriction or USER_SUBJECT.search(sentence):
        return "user_restriction", "wording restricts or addresses users"
    if CAVEAT.search(sentence):
        return "caveat", "provider acknowledges limits or possible mismatch"
    if INTENTION.search(sentence):
        return "declared_intention", "provider states what it wants or aims for"
    m = MODEL_SUBJECT.search(sentence)
    pronoun = voice == "model" and PRONOUN_SUBJECT.search(sentence) and MODAL.search(sentence)
    if (m and MODAL.search(sentence, m.end() - 1)) or pronoun or (voice == "model" and IMPERATIVE.search(sentence)):
        return "model_behavior", "model named as subject of a should/must/never-type instruction"
    if SAFEGUARD.search(sentence):
        return "safeguard_description", "describes safeguards, monitoring, or evaluation"
    return "other", "topic mentioned without a behavior, intention, or restriction"


def analyse(doc, meta, blocks, flat):
    scope = SCOPE[doc["key"]]
    voice = scope["voice"]
    groups = {c: [] for c, _ in CATEGORIES}
    other, excluded, seen = [], [], set()
    examples = sum(1 for b in blocks if b["kind"] == "example")
    for b in blocks:
        if b["kind"] in ("example", "heading"):
            continue
        for sent in sentences(b["text"]):
            tags = topic_tags(sent)
            is_safeguard = bool(SAFEGUARD.search(sent))
            is_caveat = bool(CAVEAT.search(sent) and MODEL_SUBJECT.search(sent) and CAVEAT_ABOUT.search(sent))
            if not tags and not is_safeguard and not is_caveat:
                continue
            key = compact(sent)
            if key in seen:
                continue
            seen.add(key)
            if FALSE_FRIEND.search(sent) and not [t for t in tags if t != "manipulation"]:
                excluded.append({"section": b["ref"], "quote": sent, "topics": tags,
                                 "why_excluded": "keyword concerns people manipulating the MODEL (or jailbreaks), not the model manipulating or coercing people"})
                continue
            cat, why = classify(sent, b, voice)
            if cat == "user_restriction" and is_safeguard and not tags:
                cat, why = "safeguard_description", "mentions safeguards only in passing, as something users may not circumvent"
            elif cat == "safeguard_description" and not tags and not topic_tags(b["text"]):
                continue   # a safeguard sentence in a paragraph that never touches coercion, manipulation, or autonomy
            if cat == "safeguard_description" or (is_safeguard and cat == "other"):
                cat = "safeguard_description"
            elif not tags and cat != "caveat":
                continue
            score = sum(TOPIC_WEIGHT[t] for t in tags) + (2 if cat in ("model_behavior", "declared_intention") else 0) + (1 if len(sent) < 300 else 0)
            mm = MODAL.search(sent)
            if cat == "model_behavior" and mm:       # topic word close after the should/never: the instruction is about it
                near = sent[mm.start():mm.end() + 110]
                if topic_tags(near):
                    score += 3
            item = {"section": b["ref"], "quote": sent, "topics": tags, "category": cat, "why": why, "score": score,
                    "commentary": b["kind"] == "commentary"}
            (other if cat == "other" else groups[cat]).append(item)
    for lst in list(groups.values()) + [other]:
        for it in lst:
            it["quote_verified"] = verified(it["quote"], flat)
        lst.sort(key=lambda i: (-i["score"], i["section"]))
    # safeguards: topic-bearing descriptions first
    groups["safeguard_description"].sort(key=lambda i: (-len(i["topics"]), -i["score"], i["section"]))
    concepts = []
    topic_blocks = lambda *names: [i for c in groups.values() for i in c if set(names) & set(i["topics"])]
    core = ("coercion/threats", "manipulation", "user autonomy")
    defs = [
        ("User autonomy / independent decision-making is mentioned", [i for c in groups.values() for i in c if "user autonomy" in i["topics"]]),
        ("Intended model behavior on non-manipulation / non-coercion / autonomy",
         [i for i in groups["model_behavior"] + groups["declared_intention"] if set(core) & set(i["topics"])]),
        ("Documentary description of safeguards or evaluations touching that behavior",
         [i for i in groups["safeguard_description"] if set(core) & set(i["topics"])]),
        ("Measured results about non-coercive / non-manipulative behavior",
         [{"section": b["ref"], "quote": b["text"][:200]} for b in blocks if b["kind"] in ("statement", "commentary")
          and MEASURED.search(b["text"]) and set(core) & set(topic_tags(b["text"]))]),
    ]
    for name, hits in defs:
        concepts.append({"concept": name, "count": len(hits), "status": "found" if hits else "not found in this snapshot",
                         "example": ({"section": hits[0]["section"], "quote": hits[0]["quote"]} if hits else None)})
    scope_checks = [{"quote": q, "verified": verified(q, flat)} for q in scope["scope_quotes"]]
    return {"key": doc["key"], "document": doc["title"], "url": doc["url"], "resolved_url": meta.get("resolved_url"),
            "retrieved_utc": meta["retrieved_utc"], "sha256": meta["sha256"], "bytes": meta.get("bytes"),
            "document_date": meta.get("document_date"), "http_last_modified": meta.get("http_last_modified"),
            "scope": {**{k: v for k, v in scope.items() if k != "scope_quotes"}, "scope_quotes": scope_checks},
            "groups": groups, "other_topic_mentions": other, "keyword_matches_excluded": excluded,
            "examples_excluded": examples, "concepts": concepts}


TOPIC_ANY = re.compile("|".join(rx.pattern for rx in TOPICS.values()), re.I)


def all_items(results):
    for r in results:
        for lst in r["groups"].values():
            yield from lst
        yield from r["other_topic_mentions"]
        for sc in r["scope"]["scope_quotes"]:
            yield {"quote": sc["quote"], "quote_verified": sc["verified"]}


def render_md(results):
    L = ["# ADA evidence finding (documentary)", "",
         "**Construct:** DesignNoCoercion (course tag ADA, parent claim 160.120.110; no individual L4 ID is asserted). "
         "The repo's `L4_HAI_DesignNoCoercion` is its own identifier, and its alignment with course L4 IDs is unverified.",
         "**Method:** keyword search over local snapshots; classification by wording (a heuristic to review before citing); "
         "verbatim quotations re-checked against an independent text view of each snapshot. Deterministic; no model was used.",
         "", f"> {INTERPRETATION}", "", "## Corpus summary", "",
         "| Document | Voice | Intended behavior | Declared intention | User restriction | Safeguard description | Caveat |",
         "|---|---|---|---|---|---|---|"]
    for r in results:
        g = r["groups"]
        L.append(f"| {r['document']} | {r['scope']['voice']} | {len(g['model_behavior'])} | {len(g['declared_intention'])} | "
                 f"{len(g['user_restriction'])} | {len(g['safeguard_description'])} | {len(g['caveat'])} |")
    L += ["", "Counts are sentences matched by the keyword rules in each snapshot, not measures of strength or compliance.", ""]
    L += ["**Across the corpus** (absence is limited to these five snapshots):"]
    for i, c in enumerate(results[0]["concepts"]):
        have = [r["document"] for r in results if r["concepts"][i]["count"]]
        L.append(f"- {c['concept']}: " + (", ".join(have) if have else "**not found in any snapshot**") +
                 ("" if have and len(have) == len(results) else (f" (not found in: {', '.join(r['document'] for r in results if not r['concepts'][i]['count'])})" if have else "")))
    L.append("")
    for r in results:
        sc = r["scope"]
        L += [f"## {r['document']}", f"Source: {r['url']}" + (f" (snapshot of {r['resolved_url']})" if r.get("resolved_url") and r["resolved_url"] != r["url"] else "") + "  ",
              f"Retrieved {r['retrieved_utc']}; document date/version: {r['document_date'] or 'not stated on the page'}"
              + (f"; HTTP Last-Modified: {r['http_last_modified']}" if r.get("http_last_modified") else "") + f"; sha256 `{r['sha256'][:16]}...`", "",
              f"**Scope and applicability.** {sc['publisher']} {sc['document_type']}. Applies to: {sc['applies_to']}",
              f"**Does not establish:** {sc['does_not_establish']}"]
        for q in sc["scope_quotes"]:
            L.append(f"- scope quotation {'(verified)' if q['verified'] else '(NOT VERIFIED)'}: \"{q['quote']}\"")
        L.append("")
        for cat, title in CATEGORIES:
            items = r["groups"][cat]
            L.append(f"**{title}** - {len(items)} matched" + ("" if items else " (none found in this snapshot)"))
            for it in items[:TOP_N]:
                tag = ", ".join(it["topics"]) or "no topic keyword"
                L.append(f"- {it['section']} [{tag}]: \"{it['quote']}\" {'(quote verified)' if it['quote_verified'] else '(QUOTE NOT VERIFIED)'}")
            if len(items) > TOP_N:
                L.append(f"  - ...{len(items) - TOP_N} more in ada_findings.json (ranked by topic strength)")
            L.append("")
        if r["keyword_matches_excluded"]:
            L.append("**Keyword matches judged not relevant:**")
            for d in r["keyword_matches_excluded"][:TOP_N]:
                L.append(f"- {d['section']}: \"{d['quote']}\" -- {d['why_excluded']}")
            L.append("")
        if r["examples_excluded"]:
            L += [f"{r['examples_excluded']} worked-example blocks (sample good/bad conversations) were excluded: they illustrate responses and are not statements of policy.", ""]
        L.append("**Not found in this snapshot / found:** (absence says nothing about the provider's other documents, products, or practices)")
        for c in r["concepts"]:
            line = f"- {c['concept']}: **{c['status'].upper()}**" + (f" ({c['count']} sentences)" if c["count"] else "")
            L.append(line)
        L.append("")
    L += ["## Limits",
          "- Five documents only; keyword rules can miss paraphrases (for example a sentence whose subject is 'it') and can over-match.",
          "- Classification is by wording. 'Intended behavior' and 'declared intention' are what the provider says it wants; none of it "
          "verifies implementation or behavior, and none of it applies automatically to a different product, API, or model version.",
          "- Locations: Google `item 3(b)`, Llama item/sub-item plus snapshot line (checked against the rendered pages 2026-11-09); web documents give "
          "the heading path, the page anchor where one exists (`#id`), and the paragraph number under that heading.",
          "- Doxxing/privacy provisions were not assessed here; this slice covers coercion, manipulation, threats, and autonomy only.", ""]
    return "\n".join(L)


# ---------- commands ----------
def cmd_snapshot(args):
    """Download documents that have no snapshot yet. Existing snapshots are kept (their hashes and retrieval
    dates are evidence) unless --refresh is given."""
    SNAP_DIR.mkdir(parents=True, exist_ok=True)
    for d in DOCS:
        if args.only and d["key"] != args.only:
            continue
        if (SNAP_DIR / d["file"]).exists() and not args.refresh:
            print(f"kept existing snapshot {d['file']}")
            continue
        url = d.get("fetch_url", d["url"])
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (teaching-demo)"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            data, headers, final_url = resp.read(), dict(resp.headers), resp.geturl()
        (SNAP_DIR / d["file"]).write_bytes(data)
        text = data.decode("utf-8", errors="replace")
        m = re.search(r"Last Modified:\s*([A-Za-z]+ \d+, \d{4})", text)
        title = re.search(r"<title[^>]*>(.*?)</title>", text, re.S)
        date = m.group(1) if m else None
        if not date and d["key"] == "openai_spec" and title:
            dm = re.search(r"\((\d{4}/\d{2}/\d{2})\)", title.group(1))
            date = dm.group(1) if dm else None
        meta = {"title": d["title"], "url": d["url"], "fetched_from": url, "resolved_url": final_url,
                "retrieved_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data),
                "document_date": date,
                "page_title": html.unescape(norm_ws(title.group(1))) if title else None,
                "http_last_modified": headers.get("Last-Modified") or headers.get("last-modified"),
                "http_etag": headers.get("ETag") or headers.get("etag"),
                "version_note": "Version/date as stated on the page or its URL; 'null' means the page states none."}
        (SNAP_DIR / (d["file"] + ".meta.json")).write_text(json.dumps(meta, indent=2), encoding="utf-8")
        print(f"saved {d['file']} ({len(data)} bytes) date={date}")


def cmd_run(args):
    results = []
    for d in DOCS:
        meta, blocks, flat = load_doc(d)
        results.append(analyse(d, meta, blocks, flat))
    bad = [i for i in all_items(results) if not i["quote_verified"]]
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "ada_findings.json").write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    md = render_md(results)
    (OUT_DIR / "ada_findings.md").write_text(md, encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print(md)
    print(f"Saved to {OUT_DIR}. Unverified quotations: {len(bad)}")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("run").set_defaults(fn=cmd_run)
    sp = sub.add_parser("snapshot")
    sp.set_defaults(fn=cmd_snapshot)
    sp.add_argument("--refresh", action="store_true", help="re-download even if a snapshot exists (changes its hash/date)")
    sp.add_argument("--only", help="document key, e.g. gemini_app")
    a = ap.parse_args()
    a.fn(a)
