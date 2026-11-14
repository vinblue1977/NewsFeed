"""Group items about the same story ("Full coverage"). Headline similarity only: no model, no network, cheap to run.

Two items are the same story when their headlines share enough distinctive words (Jaccard overlap, or one headline is
mostly contained in the other) and they were published close together. Clusters get a stable id (the oldest member's id)
so a story keeps its id from run to run, which is what push-notification de-duplication needs.
"""

import hashlib
import re
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

WINDOW = timedelta(hours=36)
MIN_SHARED = 3  # distinctive words two headlines must share
JACCARD = 0.4
CONTAINMENT = 0.7  # share of the shorter headline's words found in the longer

_STOPWORDS = frozenset(
    "a an and are as at be been but by can could did do does for from had has have he her his how i if in into is it its "
    "may more new not of on one or our out over says say said she so than that the their them then there these they this "
    "to up us was we were what when where which who why will with would you your after about amid just now also latest "
    "live update updates watch video photos report reports".split()
)
_WORD = re.compile(r"[a-z0-9]+")


def tokens(title: str) -> frozenset[str]:
    """Distinctive lowercase words of a headline: no stopwords, plural 's' folded, short non-numbers dropped."""
    words = _WORD.findall(title.lower().replace("’", "'").replace("'s ", " "))
    out = set()
    for word in words:
        if word in _STOPWORDS:
            continue
        if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
            word = word[:-1]
        if len(word) >= 3 or word.isdigit():
            out.add(word)
    return frozenset(out)


def _similar(a: frozenset[str], b: frozenset[str]) -> bool:
    shared = len(a & b)
    if shared < MIN_SHARED:
        return False
    return shared / len(a | b) >= JACCARD or shared / min(len(a), len(b)) >= CONTAINMENT


def cluster_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Set `cluster` on every item and return the clusters, newest activity first. Items must be sorted newest first."""
    toks = [tokens(i["title"]) for i in items]
    stamps = [datetime.fromisoformat(i["published"]) for i in items]
    members: list[list[int]] = []  # cluster -> item indexes
    index: dict[str, set[int]] = defaultdict(set)  # word -> clusters whose members use it
    assigned = [-1] * len(items)

    for n in range(len(items)):
        candidates = {c for word in toks[n] for c in index[word]}
        home = -1
        for c in sorted(candidates):
            if any(abs(stamps[m] - stamps[n]) <= WINDOW and _similar(toks[n], toks[m]) for m in members[c]):
                home = c
                break
        if home < 0:
            home = len(members)
            members.append([])
        members[home].append(n)
        assigned[n] = home
        for word in toks[n]:
            index[word].add(home)

    clusters = []
    for idxs in members:
        group = [items[m] for m in idxs]
        oldest = min(group, key=lambda i: (i["published"], i["id"]))
        lead = max(group, key=lambda i: (len(i["summary"]), i["published"]))
        cid = hashlib.sha256(oldest["id"].encode()).hexdigest()[:12]
        for item in group:
            item["cluster"] = cid
        clusters.append(
            {
                "id": cid,
                "title": lead["title"],
                "topic": lead["topic"],
                "lead": lead["id"],
                "published": max(i["published"] for i in group),
                "sources": len({i["source"] for i in group}),
                "items": [i["id"] for i in group],
            }
        )
    return sorted(clusters, key=lambda c: c["published"], reverse=True)
