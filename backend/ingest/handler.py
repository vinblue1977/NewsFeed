"""Scheduled ingest Lambda: fetch the sources, normalise, dedupe, and write the feed JSON to S3."""

import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import Any

import boto3

from ingest.cluster import cluster_items
from ingest.config import cached_location
from ingest.pipeline import collect, local_sources
from ingest.sources import SOURCES
from ingest.weather import build_weather

logger = logging.getLogger()


def previous_clusters(s3: Any) -> dict[str, str]:
    """item id -> cluster id from the feed written last time, so clusters keep their ids. Empty if there is none."""
    try:
        body = s3.get_object(Bucket=os.environ["DATA_BUCKET"], Key=f"{os.environ['DATA_PREFIX']}/feed.json")["Body"].read()
        return {i["id"]: i["cluster"] for i in json.loads(body)["items"] if "cluster" in i}
    except Exception:  # noqa: BLE001  (first run, bad file, no permission: ids are then simply derived afresh)
        logger.warning("could not read the previous feed", exc_info=True)
        return {}


def build_feed(location: dict[str, Any], previous: dict[str, str] | None = None) -> dict[str, Any]:
    items, status = collect([*SOURCES, *local_sources(location["feeds"])], location["nearby"])
    try:
        clusters = cluster_items(items, previous)
    except Exception:  # noqa: BLE001  (stories without "Full coverage" beat a stale feed)
        logger.exception("clustering failed; writing the feed without clusters")
        clusters = []
        for item in items:
            item.pop("cluster", None)
    return {"generated": datetime.now(UTC).isoformat(timespec="seconds"), "items": items, "clusters": clusters, "sources": status}


def fetch_weather(location: dict[str, Any]) -> dict[str, Any] | None:
    """The weather document, or None. Fail-soft: weather trouble is logged, never raised, so the feed is unaffected."""
    try:
        return build_weather(location["lat"], location["lon"])
    except Exception:  # noqa: BLE001  (a missing forecast must not fail the ingest run; the old weather.json stays)
        logger.exception("weather update failed")
        return None


def write_weather(s3: Any, weather: dict[str, Any] | None) -> str:
    """Write data/weather.json ("failed" if there is nothing to write or the write fails). The page shows its `generated` age."""
    if weather is None:
        return "failed"
    try:
        s3.put_object(
            Bucket=os.environ["DATA_BUCKET"],
            Key=f"{os.environ['DATA_PREFIX']}/weather.json",
            Body=json.dumps(weather, separators=(",", ":")).encode(),
            ContentType="application/json",
        )
    except Exception:  # noqa: BLE001
        logger.exception("could not write weather.json")
        return "failed"
    return "ok"


def handler(event: dict[str, Any], context: object) -> dict[str, Any]:
    """EventBridge entry point. Writes data/feed.json (kept as is if more than half the sources failed) and data/weather.json.
    The weather is fetched alongside the feed and written even when the feed run is rejected, so one never holds up the other."""
    s3 = boto3.client("s3")
    location = cached_location()
    pool = ThreadPoolExecutor(max_workers=1)
    weather_future = pool.submit(fetch_weather, location)
    weather_status = "failed"
    try:
        feed = build_feed(location, previous_clusters(s3))
        failed = [sid for sid, s in feed["sources"].items() if not s["ok"]]
        if len(failed) * 2 > len(feed["sources"]) or not feed["items"]:  # a bad run must not replace a good feed
            raise RuntimeError(f"{len(failed)} of {len(feed['sources'])} sources failed; keeping the previous feed")
        s3.put_object(
            Bucket=os.environ["DATA_BUCKET"],
            Key=f"{os.environ['DATA_PREFIX']}/feed.json",
            Body=json.dumps(feed, separators=(",", ":")).encode(),
            ContentType="application/json",
        )
    finally:
        weather_status = write_weather(s3, weather_future.result())
        pool.shutdown(wait=False)
    return {
        "status": "ok",
        "weather": weather_status,
        "items": len(feed["items"]),
        "clusters": len(feed["clusters"]),
        "sources": len(feed["sources"]),
        "failed": failed,
    }
