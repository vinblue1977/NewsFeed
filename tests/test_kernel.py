import json
from datetime import UTC, datetime

import pytest

from ingest.kernel import KERNEL_URL, KernelError, build_kernel, parse_kernel

NOW = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)


def release(moniker: str, version: str, date: str | None = "2026-11-17") -> dict[str, object]:
    return (
        {"moniker": moniker, "version": version, "released": {"isodate": date}}
        if date
        else {"moniker": moniker, "version": version}
    )


GOOD = json.dumps(
    {
        "latest_stable": {"version": "7.3.5"},
        "releases": [
            release("mainline", "7.4-rc3", "2026-11-15"),
            release("stable", "7.3.5"),
            release("stable", "7.2.15", "2026-11-01"),
            release("longterm", "6.18.64"),
            release("longterm", "6.12.118"),
        ],
    }
).encode()


def test_parse_kernel_picks_mainline_stable_and_the_newest_longterm() -> None:
    assert parse_kernel(GOOD) == [
        {"branch": "Mainline", "version": "7.4-rc3", "released": "2026-11-15"},
        {"branch": "Stable", "version": "7.3.5", "released": "2026-11-17"},
        {"branch": "Longterm", "version": "6.18.64", "released": "2026-11-17"},
    ]


def listing(mainline: dict[str, object], stable: str = "7.3.5") -> bytes:
    """A release list with the given mainline entry, a stable 7.3.5 and a longterm 6.1."""
    return json.dumps(
        {"latest_stable": {"version": stable}, "releases": [mainline, release("stable", "7.3.5"), release("longterm", "6.1")]}
    ).encode()


@pytest.mark.parametrize(
    "raw",
    [
        b"not json",
        b"[]",
        b'{"releases": []}',
        json.dumps(
            {"latest_stable": {"version": "7.3.5"}, "releases": [release("mainline", "7.4-rc3")]}
        ).encode(),  # nothing else
        listing(release("mainline", "7.4"), stable="9.9.9"),  # the named stable is not in the list
        listing(release("mainline", "<b>x</b>")),
        listing(release("mainline", "7.4\n")),  # a trailing newline is not a version
        listing(release("mainline", "7.4", "٢٠٢٦-١١-١٧")),  # nor are non-ASCII digits a date
        listing(release("mainline", "7.4", None)),
        listing(release("mainline", "7.4", "yesterday")),
    ],
)
def test_parse_kernel_rejects_anything_that_is_not_a_release_list(raw: bytes) -> None:
    with pytest.raises(KernelError):
        parse_kernel(raw)


def test_build_kernel_stamps_the_time_and_asks_kernel_org() -> None:
    asked: list[str] = []

    def getter(url: str) -> bytes:
        asked.append(url)
        return GOOD

    doc = build_kernel(getter=getter, now=NOW)
    assert asked == [KERNEL_URL]
    assert doc["generated"] == "2026-11-20T12:00:00+00:00"
    assert [r["version"] for r in doc["rows"]] == ["7.4-rc3", "7.3.5", "6.18.64"]
