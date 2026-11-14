from typing import Any

from ingest.cluster import cluster_items, tokens


def mk(id: str, title: str, source: str, published: str, summary: str = "", topic: str = "us") -> dict[str, Any]:  # noqa: A002
    return {"id": id, "title": title, "source": source, "published": published, "summary": summary, "topic": topic}


T = "2026-11-13T{}:00:00+00:00"


def test_tokens_drop_stopwords_fold_plurals_and_keep_numbers() -> None:
    assert tokens("The Rescues Are Underway in New Orleans, Mayor's office says") == {
        "rescue",
        "underway",
        "orlean",
        "mayor",
        "office",
    }
    assert tokens("Flight 15 launches") == {"flight", "15", "launche"}
    assert tokens("") == frozenset()


def test_same_story_across_sources_forms_one_cluster() -> None:
    items = [
        mk("a", "Tanker hits river cruise ship in New Orleans", "CBS", T.format("12"), "long summary here"),
        mk("b", "All rescued after cruise ship hit by tanker in New Orleans", "BBC", T.format("11")),
        mk("c", "Tanker slams into river cruise ship in New Orleans", "AP", T.format("10")),
        mk("d", "Senate passes spending bill after overnight session", "NPR", T.format("09")),
    ]
    clusters = cluster_items(items)
    assert len(clusters) == 2
    story = next(c for c in clusters if len(c["items"]) == 3)
    assert story["sources"] == 3 and story["lead"] == "a"  # the longest summary leads
    assert {i["cluster"] for i in items[:3]} == {story["id"]}
    assert items[3]["cluster"] != story["id"]
    assert [c["published"] for c in clusters] == sorted((c["published"] for c in clusters), reverse=True)


def test_two_feeds_of_one_outlet_count_as_one_source() -> None:
    items = [
        mk("a", "Storm batters coast with record winds tonight", "BBC News", T.format("12")),
        mk("b", "Storm batters coast with record winds tonight again", "BBC News", T.format("11")),
    ]
    (cluster,) = cluster_items(items)
    assert cluster["sources"] == 1 and len(cluster["items"]) == 2


def test_similar_headlines_far_apart_in_time_are_different_stories() -> None:
    items = [
        mk("a", "Fire destroys warehouse near the harbor downtown", "X", "2026-11-13T12:00:00+00:00"),
        mk("b", "Fire destroys warehouse near the harbor downtown", "Y", "2026-11-10T12:00:00+00:00"),
    ]
    assert len(cluster_items(items)) == 2


def test_a_couple_of_shared_words_is_not_enough() -> None:
    items = [
        mk("a", "Trump signs trade deal with Japan", "X", T.format("12")),
        mk("b", "Trump visits school in Ohio", "Y", T.format("11")),
    ]
    assert len(cluster_items(items)) == 2


def test_cluster_id_is_stable_when_a_newer_item_joins() -> None:
    old = [mk("a", "Fire destroys warehouse near the harbor downtown", "X", T.format("10"))]
    first = cluster_items(old)[0]["id"]
    both = [mk("b", "Fire destroys harbor warehouse downtown, officials say", "Y", T.format("12")), *old]
    (cluster,) = cluster_items(both)
    assert cluster["id"] == first and len(cluster["items"]) == 2


def test_no_items_no_clusters() -> None:
    assert cluster_items([]) == []
