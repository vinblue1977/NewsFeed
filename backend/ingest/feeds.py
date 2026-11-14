"""Fetch and parse RSS 2.0 and Atom feeds into normalised items. Everything here treats feed content as untrusted."""

import hashlib
import html
import http.client
import re
import time
import urllib.request
import xml.etree.ElementTree as ET  # noqa: S405  (DOCTYPE/ENTITY declarations are rejected first; see parse_xml)
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlsplit
from xml.parsers import expat

from ingest.articles import MAX_INPUT_CHARS, MIN_CHARS
from ingest.sources import Source

USER_AGENT = "Mozilla/5.0 (compatible; NewsPWA/1.0; personal reader)"
TIMEOUT_SECONDS = 8
ACCEPT = "application/rss+xml, application/atom+xml, application/xml, text/xml"
DEADLINE_SECONDS = 20  # total wall-clock budget per feed (the socket timeout alone resets on every byte)
MAX_BYTES = 2_000_000  # the largest feed seen is about 1.1 MB
SUMMARY_CHARS = 400
MAX_TITLE_CHARS = 300
MAX_URL_CHARS = 2000
ATOM = "{http://www.w3.org/2005/Atom}"
CONTENT = "{http://purl.org/rss/1.0/modules/content/}encoded"


class FeedError(Exception):
    """A feed could not be fetched or parsed."""


class _HttpsOnlyRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> Any:
        if urlsplit(newurl).scheme != "https":
            raise FeedError("redirected to a non-https URL")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_OPENER = urllib.request.build_opener(_HttpsOnlyRedirects)


def fetch(url: str, *, accept: str = ACCEPT, deadline_seconds: float | None = None, user_agent: str = USER_AGENT) -> bytes:
    """GET a feed over HTTPS (redirects too), with a socket timeout, a total deadline and a size cap."""
    if urlsplit(url).scheme != "https":
        raise FeedError("only https feeds are fetched")
    headers = {"User-Agent": user_agent, "Accept": accept}
    request = urllib.request.Request(url, headers=headers)  # noqa: S310  (https scheme checked above)
    deadline = time.monotonic() + (DEADLINE_SECONDS if deadline_seconds is None else deadline_seconds)
    body = bytearray()
    try:
        with _OPENER.open(request, timeout=TIMEOUT_SECONDS) as response:
            while chunk := response.read(8192):
                body += chunk
                if len(body) > MAX_BYTES:
                    raise FeedError("feed is larger than the size cap")
                if time.monotonic() > deadline:
                    raise FeedError("feed is too slow")
    except (OSError, http.client.HTTPException) as exc:  # URLError, HTTPError, timeouts, IncompleteRead
        raise FeedError(f"fetch failed: {type(exc).__name__}") from exc
    return bytes(body)


_CODE_TAGS = frozenset({"script", "style"})


class _Text(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip = 0  # depth inside <script>/<style>, whose contents are code, not text

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.skip += tag in _CODE_TAGS

    def handle_endtag(self, tag: str) -> None:
        self.skip = max(0, self.skip - (tag in _CODE_TAGS))

    def handle_data(self, data: str) -> None:
        if not self.skip:
            self.parts.append(data)


def clean_text(raw: str | None, limit: int | None = None) -> str:
    """Strip tags, decode entities, collapse whitespace, truncate on a word boundary."""
    if not raw:
        return ""
    stripper = _Text()
    stripper.feed(raw)
    stripper.close()
    text = re.sub(r"\s+", " ", "".join(stripper.parts)).strip()  # entities are already decoded
    if limit and len(text) > limit:
        text = text[:limit].rsplit(" ", 1)[0].rstrip(" ,;:-") + "…"
    return text


def _safe_url(url: str | None) -> str | None:
    """Only http(s) links with a host are kept (a feed could carry a javascript: or data: URL)."""
    if not url:
        return None
    url = url.strip()
    parts = urlsplit(url)
    # No userinfo (a "user:pw@host" authority can make a link read as another site) and a sane length.
    ok = parts.scheme in ("http", "https") and parts.netloc and "@" not in parts.netloc and len(url) <= MAX_URL_CHARS
    return url if ok else None


def _parse_date(raw: str | None) -> datetime | None:
    if not raw:
        return None
    raw = raw.strip()
    try:
        try:
            parsed = parsedate_to_datetime(raw)  # RSS: RFC 822
        except TypeError, ValueError:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))  # Atom: ISO 8601
        return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
    except TypeError, ValueError, OverflowError:
        return None


def _child(node: ET.Element, *names: str) -> str | None:
    """The text of the first matching child, including text inside child elements (Atom XHTML summaries)."""
    for name in names:
        found = node.find(name)
        if found is not None:
            text = "".join(found.itertext()).strip()
            if text:
                return text
    return None


def _atom_link(entry: ET.Element) -> str | None:
    links = entry.findall(f"{ATOM}link")
    for link in links:
        if link.get("rel", "alternate") == "alternate" and link.get("href"):
            return link.get("href")
    return links[0].get("href") if links else None


# ASCII-compatible encodings only, so the byte-level scan below sees every declaration.
_SAFE_ENCODING = re.compile(r"^(utf-?8|us-ascii|ascii|latin-?1|iso-8859-\d{1,2}|windows-125\d)$", re.IGNORECASE)
_XML_DECL = re.compile(rb"""^\s*<\?xml[^>]*encoding\s*=\s*["']([^"']+)["']""", re.IGNORECASE)
_CDATA_OR_COMMENT = re.compile(rb"<!\[CDATA\[.*?\]\]>|<!--.*?-->", re.DOTALL)


def check_safe_xml(body: bytes) -> None:
    """Refuse documents the byte-level DOCTYPE/ENTITY scan could not see through (UTF-16/32, odd encodings)."""
    start = body[3:] if body[:3] == b"\xef\xbb\xbf" else body  # a UTF-8 BOM is fine
    if b"\x00" in start[:512] or start[:2] in (b"\xff\xfe", b"\xfe\xff"):
        raise FeedError("feed is not an ASCII-compatible encoding")
    declared = _XML_DECL.match(start[:1024])
    if declared and not _SAFE_ENCODING.match(declared.group(1).decode("ascii", "replace")):
        raise FeedError("feed declares an unsupported encoding")
    # Article HTML inside CDATA or comments may legitimately contain "<!DOCTYPE html>"; only real markup counts.
    markup = _CDATA_OR_COMMENT.sub(b"", start).lower()
    if b"<!doctype" in markup or b"<!entity" in markup:
        raise FeedError("feed declares a DOCTYPE or entities; refusing to parse it")


def _inner_html(element: ET.Element) -> str:
    """Markup for an element's children, for Atom xhtml content (itertext alone would fuse its paragraphs into one run)."""
    parts = [html.escape(element.text or "", quote=False)]
    for child in element:
        tag = child.tag.rsplit("}", 1)[-1] if isinstance(child.tag, str) else "span"
        parts.append(f"<{tag}>{_inner_html(child)}</{tag}>{html.escape(child.tail or '', quote=False)}")
    return "".join(parts)


def _element_html(found: ET.Element | None) -> str:
    """The text of an entry's body element: escaped HTML arrives as text; xhtml arrives as child elements."""
    if found is None:
        return ""
    if len(found) == 0:
        return (found.text or "").strip()
    try:
        return _inner_html(found).strip()
    except RecursionError:  # an absurdly deep document: fall back to the bare text
        return "".join(found.itertext()).strip()


def _body_html(node: ET.Element, atom: bool) -> str | None:
    """The longest article HTML the entry carries (content:encoded, Atom content or summary, a long description)."""
    names = (f"{ATOM}content", f"{ATOM}summary") if atom else (CONTENT, "description")
    best = ""
    for name in names:
        text = _element_html(node.find(name))
        best = text if len(text) > len(best) else best
    return best[:MAX_INPUT_CHARS] if len(best) >= MIN_CHARS else None


def _refuse_doctype(*_args: Any) -> None:
    raise FeedError("feed declares a DOCTYPE or entities; refusing to parse it")


def parse_xml(body: bytes) -> ET.Element:
    """Parse after a pass where expat itself refuses any DOCTYPE or entity declaration (the byte scan is a first filter)."""
    guard = expat.ParserCreate()
    guard.StartDoctypeDeclHandler = _refuse_doctype
    guard.EntityDeclHandler = _refuse_doctype
    try:
        guard.Parse(body, True)
    except expat.ExpatError as exc:
        raise ET.ParseError(str(exc)) from exc
    return ET.fromstring(body)  # noqa: S314  (no DOCTYPE or entity survived the guard pass)


def parse_feed(body: bytes, source: Source) -> list[dict[str, Any]]:
    """Parse an RSS 2.0 or Atom document into items. Entries without a title, a safe link or a date are dropped."""
    check_safe_xml(body)
    try:
        root = parse_xml(body)
    except ET.ParseError as exc:
        raise FeedError(f"not valid XML: {exc}") from exc
    items: list[dict[str, Any]] = []
    for node in [*root.iter("item"), *root.iter(f"{ATOM}entry")]:
        atom = node.tag == f"{ATOM}entry"
        title = clean_text(_child(node, f"{ATOM}title") if atom else _child(node, "title"), MAX_TITLE_CHARS)
        link = _safe_url(_atom_link(node) if atom else (_child(node, "link") or _child(node, "guid")))
        published = _parse_date(
            _child(node, f"{ATOM}published", f"{ATOM}updated")
            if atom
            else _child(node, "pubDate", "{http://purl.org/dc/elements/1.1/}date")
        )
        if not (title and link and published):
            continue
        domain = (urlsplit(link).hostname or "").lower()
        source_name = source.name
        if domain == "news.google.com":  # Google News names the real publisher in <source> (and the title's " - Name" tail)
            domain = source.site or domain  # a `site:` query already says which publisher it is
            origin = node.find("source")
            if origin is not None and origin.text:
                source_name = clean_text(origin.text) or source_name
                domain = (urlsplit(origin.get("url", "")).hostname or domain).lower()
                title = title.removesuffix(f" - {source_name}")
        summary = clean_text(
            _child(node, f"{ATOM}summary", f"{ATOM}content") if atom else _child(node, "description"), SUMMARY_CHARS
        )
        item: dict[str, Any] = {
            "id": hashlib.sha256(link.encode()).hexdigest()[:16],
            "title": title,
            "url": link,
            "summary": "" if source.headline_only or summary == title else summary,
            "published": published.isoformat(timespec="seconds"),
            "source": source_name,
            "domain": domain.removeprefix("www."),
            "source_id": source.id,
            "topic": source.topic,
        }
        if source.subtopic:
            item["subtopic"] = source.subtopic
        if source.metered:
            item["metered"] = True
        elif not source.headline_only and urlsplit(link).hostname != "news.google.com":  # Google News carries only link lists
            html_body = _body_html(node, atom)
            if html_body:
                item["_html"] = html_body  # private: the ingest turns it into articles.json and removes it from the feed
        items.append(item)
    return items
