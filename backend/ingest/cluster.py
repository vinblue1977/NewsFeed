"""Group items about the same story ("Full coverage"). Headline similarity only: no model, no network, cheap to run.

Two items are the same story when their headlines share enough distinctive words (Jaccard overlap, or one headline is
mostly contained in the other) and they were published close together. A new item joins the best-matching cluster, and must
also share words with that cluster's first item, so one bridging headline cannot chain two stories together.

Cluster ids are stable across runs: a cluster inherits the id its members had in the previous feed (so a story whose oldest
item ages out keeps its id, which push-notification de-duplication needs); a brand-new story gets a hash of its oldest item.
"""

import hashlib
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from typing import Any

WINDOW = timedelta(hours=36)
MIN_SHARED = 3  # distinctive words two headlines must share
ANCHOR_SHARED = 2  # words a joining item must share with the cluster's first item (guards against chaining)
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
    words = _WORD.findall(re.sub(r"'s\b", "", title.lower().replace("’", "'")))
    out = set()
    for word in words:
        if word in _STOPWORDS:
            continue
        if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
            word = word[:-1]
        if len(word) >= 3 or word.isdigit():
            out.add(word)
    return frozenset(out)


def _score(a: frozenset[str], b: frozenset[str]) -> float:
    """0 if the headlines are not the same story, otherwise a similarity to rank matches by."""
    shared = len(a & b)
    if shared < MIN_SHARED:
        return 0.0
    jaccard = shared / len(a | b)
    contained = shared / min(len(a), len(b))
    return max(jaccard, contained) if jaccard >= JACCARD or contained >= CONTAINMENT else 0.0


def cluster_items(items: list[dict[str, Any]], previous: dict[str, str] | None = None) -> list[dict[str, Any]]:
    """Set `cluster` on every item and return the clusters, newest activity first.

    Items must be sorted newest first. `previous` maps item id -> cluster id from the last feed, for stable ids.
    """
    toks = [tokens(i["title"]) for i in items]
    stamps = [datetime.fromisoformat(i["published"]) for i in items]
    members: list[list[int]] = []  # cluster -> item indexes
    index: dict[str, set[int]] = defaultdict(set)  # word -> clusters whose members use it

    for n in range(len(items)):
        overlap = Counter(c for word in toks[n] for c in index[word])
        best, best_score = -1, 0.0
        for c, count in overlap.items():
            if count < MIN_SHARED or len(toks[n] & toks[members[c][0]]) < ANCHOR_SHARED:
                continue  # cheap necessary conditions first
            score = max(
                (_score(toks[n], toks[m]) for m in members[c] if abs(stamps[m] - stamps[n]) <= WINDOW),
                default=0.0,
            )
            if score > best_score:
                best, best_score = c, score
        if best < 0:
            best = len(members)
            members.append([])
        members[best].append(n)
        for word in toks[n]:
            index[word].add(best)

    previous = previous or {}
    taken: set[str] = set()
    clusters = []
    for idxs in sorted(members, key=len, reverse=True):  # the biggest cluster gets first claim on an inherited id
        group = [items[m] for m in idxs]
        oldest = min(group, key=lambda i: (i["published"], i["id"]))
        lead = max(group, key=lambda i: (len(i["summary"]), i["published"]))
        inherited = [
            c for c, _ in Counter(previous[i["id"]] for i in group if i["id"] in previous).most_common() if c not in taken
        ]
        cid = inherited[0] if inherited else hashlib.sha256(oldest["id"].encode()).hexdigest()[:12]
        taken.add(cid)
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
