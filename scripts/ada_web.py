"""Block extraction for the three web-page documents (OpenAI Model Spec, Claude's Constitution, Gemini app
guidelines). Standard library only. Each block is one paragraph or list item with a reproducible location:

    <heading path> [#anchor] [authority: X], paragraph N     (N counts paragraphs/list items under that heading)

Blocks inside worked examples (the Model Spec's good/bad sample conversations) are kept but marked
kind="example": they illustrate responses, they are not statements of policy, so they are never used as findings.
"""

import re
from html.parser import HTMLParser

VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
SKIP_TAGS = {"script", "style", "svg", "nav", "footer", "button", "noscript", "template", "head", "select", "form"}
SKIP_CLASS = re.compile(r"(?:^|\s)(?:sidebar|toc|breadcrumb|cookie-banner|skip-link)(?:\s|$)", re.I)
BLOCK_TAGS = {"p", "li", "h1", "h2", "h3", "h4", "h5", "h6", "td", "th", "blockquote"}
AUTHORITY_WORDS = {"Root", "Developer", "User", "Guideline", "Project", "System"}


def norm(s):
    return re.sub(r"\s+", " ", s).strip()


class _Web(HTMLParser):
    def __init__(self, main_only):
        super().__init__(convert_charrefs=True)
        self.main_only = main_only
        self.stack = []                  # [(tag, flags)]
        self.buf = []                    # open block buffers: [tag, [text...]]
        self.blocks = []
        self.headings = {}               # level -> text
        self.anchor = None
        self.authority = None
        self.para = 0
        self.badge = []

    # ---- context from the open-element stack
    def _any(self, flag):
        return any(flag in f for _, f in self.stack)

    def _active(self):
        if self._any("skip"):
            return False
        return (not self.main_only) or self._any("main")

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in VOID:
            return
        cls = a.get("class") or ""
        flags = set()
        if tag in SKIP_TAGS or SKIP_CLASS.search(cls) or a.get("aria-hidden") == "true" or "hidden" in a and tag != "html":
            flags.add("skip")
        if tag == "main":
            flags.add("main")
        if "conversation" in cls.split():
            flags.add("example")
        if "admonition" in cls:
            flags.add("commentary")
        if "section-badges" in cls or cls.split()[:1] == ["authority"]:
            flags.add("badge")
        if tag == "div" and "section" in cls.split() and a.get("id"):
            flags.add("section:" + a["id"])
        if a.get("id") and tag in ("h1", "h2", "h3", "h4", "section"):
            flags.add("hid:" + a["id"])
        self.stack.append((tag, flags))
        if self._active() and tag in BLOCK_TAGS:
            self.buf.append([tag, []])

    def handle_endtag(self, tag):
        if tag in VOID:
            return
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                active = self._active()
                del self.stack[i:]
                break
        else:
            return
        if tag in BLOCK_TAGS and self.buf and self.buf[-1][0] == tag:
            _, parts = self.buf.pop()
            text = norm("".join(parts))
            if text and (active or True) and not self._any("skip"):
                self._emit(tag, text)

    def handle_data(self, data):
        if not self._active():
            return
        if self._any("badge"):
            self.badge.append(data)
            return
        if self.buf:
            self.buf[-1][1].append(data)

    def _emit(self, tag, text):
        if not self._active() and self.main_only:
            return
        kind = "example" if self._any("example") else ("commentary" if self._any("commentary") else "statement")
        if tag[0] == "h" and len(tag) == 2:
            level = int(tag[1])
            for lv in [k for k in self.headings if k >= level]:
                del self.headings[lv]
            self.headings[level] = text
            sec = next((f[8:] for _, fl in reversed(self.stack) for f in fl if f.startswith("section:")), None)
            hid = next((f[4:] for _, fl in reversed(self.stack) for f in fl if f.startswith("hid:")), None)
            self.anchor = sec or hid
            badge = norm("".join(self.badge))
            self.authority = badge if badge in AUTHORITY_WORDS else None
            self.badge = []
            self.para = 0
            self.blocks.append({"kind": "heading", "text": text, "ref": self._path(), "paragraph": 0})
            return
        self.para += 1
        self.blocks.append({"kind": kind, "text": text, "ref": self._path(), "paragraph": self.para})

    def _path(self):
        path = " > ".join(self.headings[k] for k in sorted(self.headings)) or "(top of page)"
        extra = (f" [#{self.anchor}]" if self.anchor else "") + (f" [authority: {self.authority}]" if self.authority else "")
        return path + extra


def blocks_web(raw):
    main_only = "<main" in raw
    p = _Web(main_only)
    p.feed(raw)
    out = []
    for b in p.blocks:
        ref = b["ref"] + (f", paragraph {b['paragraph']}" if b["paragraph"] else " (heading)")
        out.append({"ref": ref, "parent": None, "text": b["text"], "kind": b["kind"]})
    return out


def flat_text_web(raw):
    """Independent, whitespace-insensitive view of the page text, used only to re-verify quotations."""
    import html
    body = re.sub(r"(?is)<(script|style|svg|template|noscript)\b.*?</\1>", " ", raw)
    return norm(html.unescape(re.sub(r"<[^>]+>", " ", body)))
