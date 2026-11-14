"""Scheduled ingest Lambda: fetch the sources, normalise, dedupe, and write the feed JSON to S3."""

import json
import logging
import os
from datetime import UTC, datetime
from typing import Any

import boto3

from ingest.cluster import cluster_items
from ingest.config import cached_location
from ingest.pipeline import collect, local_sources
from ingest.sources import SOURCES

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


def handler(event: dict[str, Any], context: object) -> dict[str, Any]:
    """EventBridge entry point. Writes data/feed.json; keeps the previous file if more than half the sources failed."""
    s3 = boto3.client("s3")
    feed = build_feed(cached_location(), previous_clusters(s3))
    failed = [sid for sid, s in feed["sources"].items() if not s["ok"]]
    if len(failed) * 2 > len(feed["sources"]) or not feed["items"]:  # a bad run must not replace a good feed
        raise RuntimeError(f"{len(failed)} of {len(feed['sources'])} sources failed; keeping the previous feed")
    s3.put_object(
        Bucket=os.environ["DATA_BUCKET"],
        Key=f"{os.environ['DATA_PREFIX']}/feed.json",
        Body=json.dumps(feed, separators=(",", ":")).encode(),
        ContentType="application/json",
    )
    return {
        "status": "ok",
        "items": len(feed["items"]),
        "clusters": len(feed["clusters"]),
        "sources": len(feed["sources"]),
        "failed": failed,
    }
