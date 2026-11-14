import pytest

from ingest.filters import block_reason, host_matches


def item(url: str, domain: str | None = None) -> dict[str, str]:
    return {"url": url, **({"domain": domain} if domain is not None else {})}


@pytest.mark.parametrize(
    ("host", "expected"),
    [
        ("nytimes.com", True),
        ("www.nytimes.com", True),
        ("cooking.nytimes.com", True),
        ("notnytimes.com", False),
        ("nytimes.com.evil.io", False),
    ],
)
def test_host_matching_is_exact_or_subdomain(host: str, expected: bool) -> None:
    assert host_matches(host, {"nytimes.com"}) is expected


def test_paywalled_and_noise_domains_are_blocked() -> None:
    assert block_reason(item("https://www.wsj.com/a")) == "paywalled"
    assert block_reason(item("https://news.google.com/rss/articles/x", "chicagotribune.com")) == "paywalled"
    assert block_reason(item("https://www.legacy.com/obituaries/x")) == "noise"
    assert block_reason(item("https://news.google.com/rss/articles/x", "maxpreps.com")) == "noise"


def test_paid_sections_of_free_sites_are_blocked() -> None:
    assert block_reason(item("https://economictimes.indiatimes.com/prime/money/abc")) == "paywalled"
    assert block_reason(item("https://www.espn.com/nfl/insider/story/x")) == "paywalled"
    assert block_reason(item("https://www.politico.com/pro/energy")) == "paywalled"


def test_free_items_pass() -> None:
    assert block_reason(item("https://www.espn.com/nfl/story/_/id/1/game-preview")) is None
    assert block_reason(item("https://economictimes.indiatimes.com/markets/stocks/news/x")) is None
    assert block_reason(item("https://www.npr.org/2026/11/13/story", "npr.org")) is None
    assert block_reason(item("not a url")) is None
