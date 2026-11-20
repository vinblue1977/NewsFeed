"""The Linux kernel's current releases for data/kernel.json, from kernel.org's own release list (free, keyless).

Three rows are kept: the mainline release candidate, the latest stable and the newest long-term series."""

import json
import re
from datetime import UTC, datetime
from typing import Any

from ingest.feeds import fetch

KERNEL_URL = "https://www.kernel.org/releases.json"
DEADLINE_SECONDS = 6
_VERSION = re.compile(r"[0-9][0-9A-Za-z.\-]{0,23}", re.ASCII)  # the same pattern as frontend/src/kernel.ts
_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")


class KernelError(Exception):
    """kernel.org's list could not be read or did not look like a release list."""


def _row(branch: str, release: dict[str, Any]) -> dict[str, str]:
    version = release.get("version")
    released = (release.get("released") or {}).get("isodate")
    if not (isinstance(version, str) and _VERSION.fullmatch(version) and isinstance(released, str) and _DATE.fullmatch(released)):
        raise KernelError(f"unreadable {branch} release")
    return {"branch": branch, "version": version, "released": released}


def parse_kernel(raw: bytes) -> list[dict[str, str]]:
    """[{"branch", "version", "released"}] for Mainline, Stable and Longterm; raises KernelError if any is missing."""
    try:
        doc = json.loads(raw)
        releases = [r for r in doc["releases"] if isinstance(r, dict)]
        stable_version = doc["latest_stable"]["version"]
    except (ValueError, KeyError, TypeError) as exc:
        raise KernelError("not a kernel.org release list") from exc

    def first(moniker: str, version: str | None = None) -> dict[str, Any]:
        for r in releases:
            if r.get("moniker") == moniker and (version is None or r.get("version") == version):
                return r
        raise KernelError(f"no {moniker} release in the list")

    return [
        _row("Mainline", first("mainline")),
        _row("Stable", first("stable", stable_version)),
        _row("Longterm", first("longterm")),
    ]


def build_kernel(*, getter: Any = None, now: datetime | None = None) -> dict[str, Any]:
    """{"generated", "rows": [...]}; raises KernelError (or the fetch error) so the previous file stays."""
    now = now or datetime.now(UTC)
    get = getter or (lambda url: fetch(url, accept="application/json", deadline_seconds=DEADLINE_SECONDS))
    return {"generated": now.isoformat(timespec="seconds"), "rows": parse_kernel(get(KERNEL_URL))}
