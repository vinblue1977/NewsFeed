"""Scheduled ingest Lambda: fetch the sources, normalise, dedupe, and write the feed JSON to S3."""

import json
import logging
import os
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import Any

import boto3

from ingest.articles import build_articles, dumps
from ingest.cluster import cluster_items
from ingest.config import cached_location
from ingest.images import attach_images, known_images
from ingest.markets import build_markets
from ingest.pipeline import collect, local_sources
from ingest.scores import build_scores
from ingest.sources import SOURCES
from ingest.weather import build_weather

logger = logging.getLogger()
PICTURE_CUTOFF_SECONDS = 50  # past this, no new pictures are fetched (the Lambda timeout is 90 s)


def previous_state(s3: Any) -> tuple[dict[str, str], dict[str, str]]:
    """(item id -> cluster id, item id -> picture file) from the feed written last time, so clusters keep their ids and
    pictures are not fetched twice. Both empty if there is no usable feed."""
    try:
        body = s3.get_object(Bucket=os.environ["DATA_BUCKET"], Key=f"{os.environ['DATA_PREFIX']}/feed.json")["Body"].read()
        items = json.loads(body)["items"]
        return {i["id"]: i["cluster"] for i in items if "cluster" in i}, known_images(items)
    except Exception:  # noqa: BLE001  (first run, bad file, no permission: ids are then simply derived afresh)
        logger.warning("could not read the previous feed", exc_info=True)
        return {}, {}


def build_feed(location: dict[str, Any], previous: dict[str, str] | None = None) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """The feed and the articles document (None if it could not be built). Items flagged `full` are exactly those in it."""
    items, status = collect([*SOURCES, *local_sources(location["feeds"])], location["nearby"])
    bodies = {i["id"]: i.pop("_html") for i in items if "_html" in i}  # the raw HTML never goes into feed.json or clustering
    try:
        clusters = cluster_items(items, previous)
    except Exception:  # noqa: BLE001  (stories without "Full coverage" beat a stale feed)
        logger.exception("clustering failed; writing the feed without clusters")
        clusters = []
        for item in items:
            item.pop("cluster", None)
    generated = datetime.now(UTC).isoformat(timespec="seconds")
    articles: dict[str, Any] | None = None
    try:
        articles, with_text = build_articles(items, bodies, generated)
        for item in items:
            if item["id"] in with_text:
                item["full"] = True
    except Exception:  # noqa: BLE001  (a feed without full text beats no feed)
        logger.exception("articles failed; writing the feed without full text")
        articles = None
        for item in items:
            item.pop("full", None)
    return {"generated": generated, "items": items, "clusters": clusters, "sources": status}, articles


def soft(name: str, build: Callable[[], dict[str, Any]]) -> dict[str, Any] | None:
    """A side document (weather, markets, scores), or None. Fail-soft: trouble is logged, never raised; the feed is unaffected."""
    try:
        return build()
    except Exception:  # noqa: BLE001  (a missing side document must not fail the ingest run; its old file stays)
        logger.exception("%s update failed", name)
        return None


def write_doc(s3: Any, name: str, doc: dict[str, Any] | None) -> str:
    """Write data/<name>.json ("failed" if there is nothing to write or the write fails). Each document carries `generated`."""
    if doc is None:
        return "failed"
    try:
        s3.put_object(
            Bucket=os.environ["DATA_BUCKET"],
            Key=f"{os.environ['DATA_PREFIX']}/{name}.json",
            Body=dumps(doc),
            ContentType="application/json",
        )
    except Exception:  # noqa: BLE001
        logger.exception("could not write %s.json", name)
        return "failed"
    return "ok"


def handler(event: dict[str, Any], context: object) -> dict[str, Any]:
    """EventBridge entry point. Writes data/feed.json (kept as is if more than half the sources failed), plus weather.json,
    markets.json and scores.json. Those three are fetched alongside the feed and written even when the feed run is rejected,
    so none of them holds up another."""
    started = time.monotonic()
    s3 = boto3.client("s3")
    location = cached_location()
    pool = ThreadPoolExecutor(max_workers=3)
    side = {
        "weather": pool.submit(soft, "weather", lambda: build_weather(location["lat"], location["lon"])),
        "markets": pool.submit(soft, "markets", lambda: build_markets(location.get("tickers", []))),
        "scores": pool.submit(soft, "scores", build_scores),
    }
    statuses: dict[str, str] = {}
    articles_status = "failed"
    try:
        clusters_before, images_before = previous_state(s3)
        feed, articles = build_feed(location, clusters_before)
        failed = [sid for sid, s in feed["sources"].items() if not s["ok"]]
        if len(failed) * 2 > len(feed["sources"]) or not feed["items"]:  # a bad run must not replace a good feed
            raise RuntimeError(f"{len(failed)} of {len(feed['sources'])} sources failed; keeping the previous feed")
        articles_status = write_doc(s3, "articles", articles)  # first, so a `full` flag in the feed always has its text
        if articles_status != "ok":
            for item in feed["items"]:
                item.pop("full", None)  # the flag must never promise text that is not there
        try:
            attach_images(
                s3,
                os.environ["DATA_BUCKET"],
                os.environ["DATA_PREFIX"],
                feed["items"],
                images_before,
                fetch_new=time.monotonic() - started < PICTURE_CUTOFF_SECONDS,  # a late run must still write the feed
            )
        except Exception:  # noqa: BLE001  (a feed without pictures beats no feed)
            logger.exception("pictures failed; writing the feed without them")
            for item in feed["items"]:
                item.pop("_image", None)
                item.pop("img", None)
        s3.put_object(
            Bucket=os.environ["DATA_BUCKET"],
            Key=f"{os.environ['DATA_PREFIX']}/feed.json",
            Body=dumps(feed),
            ContentType="application/json",
        )
    finally:
        statuses = {name: write_doc(s3, name, future.result()) for name, future in side.items()}
        pool.shutdown(wait=False)
    return {
        "status": "ok",
        "articles": articles_status,
        **statuses,
        "items": len(feed["items"]),
        "clusters": len(feed["clusters"]),
        "sources": len(feed["sources"]),
        "failed": failed,
    }
