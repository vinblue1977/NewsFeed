"""Pictures for ESPN NFL stories. ESPN's RSS names none, but its news API (the one behind the scoreboard) gives a photo per
story. The two are matched on the story id in the link; a story with no match simply stays without a picture."""

import json
import logging
import re
from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit

from ingest.feeds import fetch

logger = logging.getLogger()

NEWS_URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/news?limit=50"
SOURCE_ID = "espn-nfl"
PHOTO_HOST = "a.espncdn.com"  # real photos live here; the other entries are game graphics and video stills
MIN_WIDTH = 500
STORY_ID = re.compile(r"/id/(\d+)")
DEADLINE_SECONDS = 4  # a slow ESPN API must not hold up the feed


def _get(url: str) -> bytes:
    return fetch(url, accept="application/json", deadline_seconds=DEADLINE_SECONDS)


def _story_id(url: Any) -> str | None:
    found = STORY_ID.search(url) if isinstance(url, str) else None
    return found.group(1) if found else None


def _best_photo(images: Any) -> str | None:
    """The widest photo of at least MIN_WIDTH, from ESPN's own photo host over https."""
    best: tuple[int, str] | None = None
    for image in images if isinstance(images, list) else []:
        if not isinstance(image, dict):
            continue
        url, width = image.get("url"), image.get("width")
        if not isinstance(url, str) or not isinstance(width, int) or width < MIN_WIDTH:
            continue
        parts = urlsplit(url)
        if parts.scheme == "https" and parts.netloc == PHOTO_HOST and (best is None or width > best[0]):
            best = (width, url)
    return best[1] if best else None


def parse_pictures(body: bytes) -> dict[str, str]:
    """{story id: picture URL} from the news API's JSON; {} if it is not usable."""
    try:
        articles = json.loads(body)["articles"]
    except ValueError, KeyError, TypeError:
        return {}
    found: dict[str, str] = {}
    for article in articles if isinstance(articles, list) else []:
        try:
            story, photo = _story_id(article["links"]["web"]["href"]), _best_photo(article.get("images"))
        except KeyError, TypeError:
            continue
        if story and photo:
            found[story] = photo
    return found


def add_pictures(items: list[dict[str, Any]], getter: Callable[[str], bytes] | None = None) -> int:
    """Set the private `_image` of ESPN NFL items that have none. Fail-soft: any trouble means no pictures, never an error."""
    wanted = [i for i in items if i.get("source_id") == SOURCE_ID and not i.get("_image")]
    if not wanted:
        return 0
    try:
        pictures = parse_pictures((getter or _get)(NEWS_URL))
    except Exception:  # noqa: BLE001  (a feed without these pictures beats no feed)
        return 0
    added = 0
    for item in wanted:
        photo = pictures.get(_story_id(item.get("url")) or "")
        if photo:
            item["_image"] = photo
            added += 1
    logger.info("espn pictures: %d of %d stories matched (the API lists only the newest)", added, len(wanted))
    return added
