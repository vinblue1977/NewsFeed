"""Item filters: paywalled publishers, low-value noise, and known paid-content URL patterns.

Free articles only (see PLAN.md). Paywall status cannot be detected from a feed, so this is a block list plus a few
URL patterns, extended by hand when a source turns out to be gated. Metered sources are kept and flagged instead.
"""

import re
from typing import Any
from urllib.parse import urlsplit

# Hard paywalls: never shown, whichever feed (or Google News result) carries them.
PAYWALLED_DOMAINS = frozenset(
    {
        "nytimes.com",
        "wsj.com",
        "washingtonpost.com",
        "ft.com",
        "bloomberg.com",
        "economist.com",
        "barrons.com",
        "chicagotribune.com",
        "theathletic.com",
        "newyorker.com",
        "thetimes.co.uk",
        "telegraph.co.uk",
        "theinformation.com",
        "businessinsider.com",
    }
)

# Not paywalled, but never worth a card: obituaries, school-sports score boxes, wire press releases.
NOISE_DOMAINS = frozenset(
    {
        "legacy.com",
        "maxpreps.com",
        "financialcontent.com",
        "prnewswire.com",
        "businesswire.com",
        "globenewswire.com",
        "einpresswire.com",
        "openpr.com",
    }
)

# (domain, path regex) for paid sections inside an otherwise free site. Best effort: the patterns are the sites' own
# URL conventions for subscriber content, and none appeared in the feeds when this was written.
PAID_PATHS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("economictimes.indiatimes.com", re.compile(r"/prime/|/et-prime/", re.IGNORECASE)),
    ("espn.com", re.compile(r"/insider/|/espn-plus/|/espnplus/", re.IGNORECASE)),
    ("politico.com", re.compile(r"/pro/", re.IGNORECASE)),
)


def host_matches(host: str, domains: frozenset[str] | set[str]) -> bool:
    """True if `host` is one of `domains` or a subdomain of one."""
    host = host.lower().removeprefix("www.")
    return any(host == d or host.endswith("." + d) for d in domains)


def block_reason(item: dict[str, Any]) -> str | None:
    """Why an item must not be shown ('paywalled' or 'noise'), or None. Uses the item's `domain` and its URL."""
    domain = item.get("domain") or urlsplit(item["url"]).hostname or ""
    if host_matches(domain, PAYWALLED_DOMAINS):
        return "paywalled"
    if host_matches(domain, NOISE_DOMAINS):
        return "noise"
    path = urlsplit(item["url"]).path
    for site, pattern in PAID_PATHS:
        if host_matches(domain, {site}) and pattern.search(path):
            return "paywalled"
    return None
