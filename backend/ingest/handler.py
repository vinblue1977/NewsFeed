"""Scheduled ingest Lambda (stub): will fetch feeds, normalise, dedupe and write feed JSON to S3 (Phase 2)."""

import json
from typing import Any

from ingest.config import cached_location


def handler(event: dict[str, Any], context: object) -> dict[str, Any]:
    """EventBridge entry point. Reads the location config (fails loudly if missing); does nothing else yet."""
    location = cached_location()
    return {"status": "ok", "sources": 0, "local_feeds": len(location["feeds"]), "event": json.dumps(event, sort_keys=True)}
