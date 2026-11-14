"""Full article text for data/articles.json.

Some feeds carry the whole article in the entry (RSS content:encoded, Atom content, a long description). feeds.parse_feed
keeps that HTML on the item as `_html`; the ingest moves it into a side dict (so it is not carried through clustering),
and this module turns it into plain-text blocks, applies a budget, and says which items made it. The feed JSON only gets a
`full` flag for items that were really written, and never carries the HTML.

Output: {"generated": "<ISO>", "articles": {"<item id>": [{"t": "p"|"h"|"li"|"q", "x": "<plain text>"}, ...]}}
`generated` is the same value as the feed's, so a page can tell whether its two files belong together.
Plain text only: no HTML, links or images ever reach the page.
"""

import json
import re
from html.parser import HTMLParser
from typing import Any

MAX_ARTICLES = 60
MAX_CHARS = 8000  # per article; the page says "read the rest on their site" after the cut
MIN_CHARS = 600  # below this the body is a teaser that merely repeats the summary
MAX_BYTES = 450_000  # the whole document
MAX_INPUT_CHARS = 120_000  # the HTML is cut here (a long article is well under this) before it is parsed

# Elements whose contents are never prose: code, media, forms, page furniture, tables. (Void tags such as <embed> have no
# contents and no end tag, so they are not listed: they would switch skipping on and never off.)
_SKIP = frozenset(
    {
        "script", "style", "iframe", "noscript", "template", "svg", "math", "object", "form", "button", "select",
        "textarea", "figure", "figcaption", "picture", "video", "audio", "canvas", "map", "table", "nav", "aside",
        "header", "footer", "head", "title",
    }
)  # fmt: skip
_LITERAL = frozenset({"code", "pre", "kbd", "samp", "tt"})  # text in these is code on purpose: kept even if it looks like code
_HEADINGS = frozenset({"h1", "h2", "h3", "h4", "h5", "h6"})
_BREAKS = frozenset({"p", "div", "br", "hr", "ul", "ol", "section", "article", "pre", "dl", "dt", "dd"})
# C0 controls (not tab/newline), DEL, line/paragraph separators, zero-width space and the byte-order mark. Joiners are kept:
# scripts such as Bengali and Malayalam need them.
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f\u200b\u2028\u2029\ufeff]")
_SPACE = re.compile(r"\s+")
_FOOTER = re.compile(r"^the post .{0,300} appeared first on ", re.IGNORECASE)  # WordPress's link-back line

# Code that reached the text as plain words. Some feeds strip a <script> tag but leave its contents behind (The Verge's ad
# embeds do: "window.HYPE_DESK_CONFIG = { ... };"), so there is no tag left to skip. These patterns are deliberately narrow so
# prose that merely mentions code survives: a block is dropped only if it STARTS like a script or real HTML markup, or is an
# object or style-rule literal. Text that sat inside <code> or <pre> is deliberate code, and is never dropped (see _Blocks).
_CODE_START = re.compile(
    r"""^\s*(?:
        (?:window|document|globalThis|self)\.[A-Za-z_$][\w$]*\s*(?:=|\()      # window.FOO = ... / document.write(...)
        |(?:var|let|const)\s+[A-Za-z_$][\w$]*\s*=                          # const x = ...
        |(?:async\s+)?function\b\s*[\w$]*\s*\(                              # function f(...
        |\(\s*(?:function|\(\)\s*=>)|!\s*function\b                          # (function () {...  /  !function
        |(?:import|export)\b[^.!?]{0,200}\bfrom\s+['"]                       # import x from 'y'
        |[\[{]\s*["'][\w$-]+["']\s*:                                        # a JSON object or array
        |</?(?i:div|span|p|a|img|script|style|link|meta|iframe|ul|ol|li|table|tr|td|br|hr|section|figure|button|svg|form|input|
            h[1-6]|b|i|em|strong)\b[^<>]{0,200}>|<!--                       # markup shown as text (real tag names only)
        |@(?:media|font-face|import|keyframes)\b                             # CSS at-rules
    )""",
    re.VERBOSE,
)
_KEY_VALUE = re.compile(r"""[A-Za-z_$][\w$-]*\s*:\s*(?:["'\[{\d]|true\b|false\b|null\b)""")
_OBJECT_OPEN = re.compile(r"(?:^|[=(:,\[])\s*\{")  # a brace that opens an object: after =, (, :, comma, [ or at the start
_CSS_RULE = re.compile(r"[^{}]{1,120}\{\s*[\w-]+\s*:[^{}]*;[^{}]*\}")

# Page furniture that arrives as its own block: a lone label, a newsletter promo, a sponsor line. Whole-block matches only, so a
# sentence that merely uses these words is kept.
_BOILERPLATE = re.compile(
    r"^(?:comments?|share|advertisement|related|read more)[:.]?$"
    r"|^sign up for (?:the|our) [^.!?]{1,80}(?:email|newsletter)s?\.?$"
    r"|^sponsored by [^.!?]{1,60}:.{0,250}$",
    re.IGNORECASE,
)


def is_boilerplate(text: str) -> bool:
    """True for a block that is page furniture (see above) rather than article text."""
    return bool(_BOILERPLATE.search(text))


def looks_like_code(text: str) -> bool:
    """True for a block that is script, JSON, CSS or markup rather than prose (see the patterns above)."""
    if _CODE_START.search(text):
        return True
    if "{" in text and "}" in text:
        object_literal = bool(_OBJECT_OPEN.search(text)) and len(_KEY_VALUE.findall(text)) >= 3
        return object_literal or bool(_CSS_RULE.search(text))
    return False


class _Blocks(HTMLParser):
    """HTML -> [{"t", "x"}]. Tolerant of unclosed and nested tags; anything unknown is treated as inline text.
    A paragraph inside a list item, quote or heading keeps that outer kind (headings beat list items beat quotes)."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[dict[str, str]] = []
        self.parts: list[str] = []
        self.skipping: str | None = None  # the skipped element we are inside, and how deep that same tag nests
        self.skip_depth = 0
        self.inside = {"h": 0, "li": 0, "q": 0}
        self.literal_depth = 0  # inside <code>/<pre> and the like: code written on purpose
        self.literal = False  # the block being built contains such text, so it is never judged as leaked code

    def _kind(self) -> str:
        return "h" if self.inside["h"] else "li" if self.inside["li"] else "q" if self.inside["q"] else "p"

    def _flush(self) -> None:
        text = _SPACE.sub(" ", _CONTROL.sub("", "".join(self.parts))).strip()
        self.parts = []
        literal, self.literal = self.literal, False
        if not text or _FOOTER.search(text) or is_boilerplate(text) or (looks_like_code(text) and not literal):
            return
        self.blocks.append({"t": self._kind(), "x": text})

    @staticmethod
    def _container(tag: str) -> str | None:
        return "h" if tag in _HEADINGS else "li" if tag == "li" else "q" if tag == "blockquote" else None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self.skipping:
            self.skip_depth += tag == self.skipping
            return
        if tag in _SKIP:
            self._flush()
            self.skipping, self.skip_depth = tag, 1
            return
        container = self._container(tag)
        if container or tag in _BREAKS:
            self._flush()
        if container:
            self.inside[container] += 1
        if tag in _LITERAL:
            self.literal_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if self.skipping:
            if tag == self.skipping:
                self.skip_depth -= 1
                if self.skip_depth == 0:
                    self.skipping = None
            return
        container = self._container(tag)
        if container or tag in _BREAKS:
            self._flush()
        if container:
            self.inside[container] = max(0, self.inside[container] - 1)
        if tag in _LITERAL:
            self.literal_depth = max(0, self.literal_depth - 1)

    def handle_data(self, data: str) -> None:
        if not self.skipping:
            self.parts.append(data)
            self.literal = self.literal or self.literal_depth > 0

    def close(self) -> None:
        super().close()
        self._flush()


def html_to_blocks(raw: str | None) -> list[dict[str, str]]:
    """Plain-text blocks from an HTML fragment. Never raises: a body it cannot read gives no blocks."""
    if not raw:
        return []
    parser = _Blocks()
    try:
        parser.feed(raw[:MAX_INPUT_CHARS])
        parser.close()
    except Exception:  # noqa: BLE001  (html.parser can reject odd markup; that article is simply not shown in full)
        return []
    return parser.blocks


def _text_length(blocks: list[dict[str, str]]) -> int:
    return sum(len(b["x"]) for b in blocks)


def _trim(blocks: list[dict[str, str]]) -> list[dict[str, str]]:
    """The first blocks that fit MAX_CHARS, cut at a block boundary. A first block that is itself too long is cut at a word."""
    kept: list[dict[str, str]] = []
    total = 0
    for block in blocks:
        if total + len(block["x"]) > MAX_CHARS:
            if not kept:
                kept.append({"t": block["t"], "x": block["x"][:MAX_CHARS].rsplit(" ", 1)[0].rstrip(" ,;:-") + "…"})
            break
        kept.append(block)
        total += len(block["x"])
    return kept


def dumps(doc: Any) -> bytes:
    """The one way every data file is serialised: compact UTF-8 JSON (the size budget below counts these same bytes)."""
    return json.dumps(doc, separators=(",", ":"), ensure_ascii=False).encode()


def build_articles(items: list[dict[str, Any]], bodies: dict[str, str], generated: str) -> tuple[dict[str, Any], set[str]]:
    """The articles document and the ids in it. `bodies` maps item id -> article HTML. Newest first, at most MAX_ARTICLES,
    each cut to MAX_CHARS, the whole document under MAX_BYTES; an article under MIN_CHARS is a teaser and is left out."""
    articles: dict[str, list[dict[str, str]]] = {}
    size = len(dumps({"generated": generated, "articles": {}}))
    for item in sorted(items, key=lambda i: i["published"], reverse=True):
        if len(articles) >= MAX_ARTICLES:
            break
        html = bodies.get(item["id"])
        if item.get("metered") or not html:
            continue
        blocks = _trim(html_to_blocks(html))
        if _text_length(blocks) < MIN_CHARS:
            continue
        entry_bytes = len(dumps({item["id"]: blocks})) + 1
        if size + entry_bytes > MAX_BYTES:
            break
        articles[item["id"]] = blocks
        size += entry_bytes
    return {"generated": generated, "articles": articles}, set(articles)
