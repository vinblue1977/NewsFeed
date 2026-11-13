"""Scheduled ingest Lambda: fetch the sources, normalise, dedupe, and write the feed JSON to S3."""

import json
import os
from datetime import UTC, datetime
from typing import Any

import boto3

from ingest.config import cached_location
from ingest.pipeline import collect, local_sources
from ingest.sources import SOURCES


def build_feed(location: dict[str, Any]) -> dict[str, Any]:
    items, status = collect([*SOURCES, *local_sources(location["feeds"])], location["nearby"])
    return {"generated": datetime.now(UTC).isoformat(timespec="seconds"), "items": items, "sources": status}


def handler(event: dict[str, Any], context: object) -> dict[str, Any]:
    """EventBridge entry point. Writes data/feed.json; keeps the previous file if more than half the sources failed."""
    feed = build_feed(cached_location())
    failed = [sid for sid, s in feed["sources"].items() if not s["ok"]]
    if len(failed) * 2 > len(feed["sources"]) or not feed["items"]:  # a bad run must not replace a good feed
        raise RuntimeError(f"{len(failed)} of {len(feed['sources'])} sources failed; keeping the previous feed")
    boto3.client("s3").put_object(
        Bucket=os.environ["DATA_BUCKET"],
        Key=f"{os.environ['DATA_PREFIX']}/feed.json",
        Body=json.dumps(feed, separators=(",", ":")).encode(),
        ContentType="application/json",
    )
    return {"status": "ok", "items": len(feed["items"]), "sources": len(feed["sources"]), "failed": failed}
