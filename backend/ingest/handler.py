"""Scheduled ingest Lambda (stub): will fetch feeds, normalise, dedupe and write feed JSON to S3 (Phase 2)."""

import json
from typing import Any


def handler(event: dict[str, Any], context: object) -> dict[str, Any]:
    """Entry point for the EventBridge schedule. Does nothing yet."""
    return {"status": "ok", "sources": 0, "event": json.dumps(event, sort_keys=True)}
