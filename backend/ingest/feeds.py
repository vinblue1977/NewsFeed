"""Fetch and parse RSS 2.0 and Atom feeds into normalised items. Everything here treats feed content as untrusted."""

import hashlib
import html
import re
import urllib.request
import xml.etree.ElementTree as ET  # noqa: S405  (DOCTYPE/ENTITY declarations are rejected before parsing; see parse_feed)
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlsplit

from ingest.sources import Source

USER_AGENT = "Mozilla/5.0 (compatible; NewsPWA/1.0; personal reader)"
TIMEOUT_SECONDS = 8
ACCEPT = "application/rss+xml, application/atom+xml, application/xml, text/xml"
MAX_BYTES = 2_000_000  # the largest feed seen is about 1.1 MB
SUMMARY_CHARS = 400
ATOM = "{http://www.w3.org/2005/Atom}"


class FeedError(Exception):
    """A feed could not be fetched or parsed."""


def fetch(url: str) -> bytes:
    """GET a feed over HTTPS, with a timeout and a size cap."""
    if urlsplit(url).scheme != "https":
        raise FeedError("only https feeds are fetched")
    headers = {"User-Agent": USER_AGENT, "Accept": ACCEPT}
    request = urllib.request.Request(url, headers=headers)  # noqa: S310  (https scheme checked above)
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:  # noqa: S310
            body = response.read(MAX_BYTES + 1)
    except OSError as exc:  # URLError, HTTPError, timeouts and connection errors are all OSError
        raise FeedError(f"fetch failed: {exc}") from exc
    if len(body) > MAX_BYTES:
        raise FeedError("feed is larger than the size cap")
    return body


class _Text(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip = 0  # depth inside <script>/<style>, whose contents are code, not text

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.skip += tag in ("script", "style")

    def handle_endtag(self, tag: str) -> None:
        self.skip = max(0, self.skip - (tag in ("script", "style")))

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
    text = re.sub(r"\s+", " ", html.unescape("".join(stripper.parts))).strip()
    if limit and len(text) > limit:
        text = text[:limit].rsplit(" ", 1)[0].rstrip(" ,;:-") + "…"
    return text


def _safe_url(url: str | None) -> str | None:
    """Only http(s) links with a host are kept (a feed could carry a javascript: or data: URL)."""
    if not url:
        return None
    parts = urlsplit(url.strip())
    return url.strip() if parts.scheme in ("http", "https") and parts.netloc else None


def _parse_date(raw: str | None) -> datetime | None:
    if not raw:
        return None
    raw = raw.strip()
    try:
        parsed = parsedate_to_datetime(raw)  # RSS: RFC 822
    except TypeError, ValueError:
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))  # Atom: ISO 8601
        except ValueError:
            return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _child(node: ET.Element, *names: str) -> str | None:
    for name in names:
        found = node.find(name)
        if found is not None and (found.text or "").strip():
            return found.text
    return None


def _atom_link(entry: ET.Element) -> str | None:
    links = entry.findall(f"{ATOM}link")
    for link in links:
        if link.get("rel", "alternate") == "alternate" and link.get("href"):
            return link.get("href")
    return links[0].get("href") if links else None


def parse_feed(body: bytes, source: Source) -> list[dict[str, Any]]:
    """Parse an RSS 2.0 or Atom document into items. Entries without a title, a safe link or a date are dropped."""
    head = body[:4096].lower()
    if b"<!doctype" in head or b"<!entity" in body.lower():
        raise FeedError("feed declares a DOCTYPE or entities; refusing to parse it")
    try:
        root = ET.fromstring(body)  # noqa: S314
    except ET.ParseError as exc:
        raise FeedError(f"not valid XML: {exc}") from exc
    items: list[dict[str, Any]] = []
    for node in [*root.iter("item"), *root.iter(f"{ATOM}entry")]:
        atom = node.tag == f"{ATOM}entry"
        title = clean_text(_child(node, f"{ATOM}title") if atom else _child(node, "title"))
        link = _safe_url(_atom_link(node) if atom else (_child(node, "link") or _child(node, "guid")))
        published = _parse_date(
            _child(node, f"{ATOM}published", f"{ATOM}updated")
            if atom
            else _child(node, "pubDate", "{http://purl.org/dc/elements/1.1/}date")
        )
        if not (title and link and published):
            continue
        summary = clean_text(
            _child(node, f"{ATOM}summary", f"{ATOM}content") if atom else _child(node, "description"), SUMMARY_CHARS
        )
        item: dict[str, Any] = {
            "id": hashlib.sha256(link.encode()).hexdigest()[:16],
            "title": title,
            "url": link,
            "summary": "" if summary == title else summary,
            "published": published.isoformat(timespec="seconds"),
            "source": source.name,
            "source_id": source.id,
            "topic": source.topic,
        }
        if source.subtopic:
            item["subtopic"] = source.subtopic
        if source.metered:
            item["metered"] = True
        items.append(item)
    return items
