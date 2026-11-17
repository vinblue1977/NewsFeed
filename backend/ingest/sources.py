"""The national source list. Each source has an `enabled` flag, so dropping a noisy one is a one-line change.

Local feeds are not here: their URLs live in the SSM location parameter (see config.py).
`metered` marks sources that may show a soft paywall after a few free reads: kept, but flagged in the feed JSON.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Source:
    id: str
    name: str
    url: str
    topic: str  # us | world | india | sports | tech | business | local
    subtopic: str | None = None  # a Browse tile: sports, tech or business ids, e.g. nfl, f1, gadgets
    enabled: bool = True
    metered: bool = False
    headline_only: bool = False  # Google News `site:` feeds: title, source and link, no summary
    site: str | None = None  # Google News `site:` query: the publisher's domain when an item has no <source>
    trusted: bool = (
        False  # a Google News search already scoped to the places (not one limited to a publisher): skip the place filter
    )
    sitemap: bool = False  # the URL is a Google News sitemap (title, link, time), not RSS or Atom


def _s(id: str, name: str, url: str, topic: str, subtopic: str | None = None, *, metered: bool = False) -> Source:  # noqa: A002
    return Source(id, name, url, topic, subtopic, metered=metered)


SOURCES: tuple[Source, ...] = (
    # US
    _s("npr", "NPR", "https://feeds.npr.org/1001/rss.xml", "us"),
    _s("pbs", "PBS NewsHour", "https://www.pbs.org/newshour/feeds/rss/headlines", "us"),
    _s("abc", "ABC News", "https://abcnews.go.com/abcnews/topstories", "us"),
    _s("cbs", "CBS News", "https://www.cbsnews.com/latest/rss/main", "us"),
    _s("nbc", "NBC News", "https://feeds.nbcnews.com/nbcnews/public/news", "us"),
    _s("thehill", "The Hill", "https://thehill.com/feed/", "us"),
    _s("bbc-us", "BBC News", "https://feeds.bbci.co.uk/news/world/us_and_canada/rss.xml", "us"),
    # US politics
    _s("politico", "Politico", "https://rss.politico.com/politics-news.xml", "us"),
    _s("npr-politics", "NPR", "https://feeds.npr.org/1014/rss.xml", "us"),
    _s("guardian-uspolitics", "The Guardian", "https://www.theguardian.com/us-news/us-politics/rss", "us"),
    _s("pbs-politics", "PBS NewsHour", "https://www.pbs.org/newshour/feeds/rss/politics", "us"),
    _s("cbs-politics", "CBS News", "https://www.cbsnews.com/latest/rss/politics", "us"),
    _s("abc-politics", "ABC News", "https://abcnews.go.com/abcnews/politicsheadlines", "us"),
    _s("thehill-admin", "The Hill", "https://thehill.com/homenews/administration/feed/", "us"),
    # World
    _s("bbc-world", "BBC News", "https://feeds.bbci.co.uk/news/world/rss.xml", "world"),
    _s("nyt-world", "The New York Times", "https://rss.nytimes.com/services/xml/rss/nyt/World.xml", "world", metered=True),
    _s("dw", "DW", "https://rss.dw.com/xml/rss-en-world", "world"),
    _s("france24", "France 24", "https://www.france24.com/en/rss", "world"),
    _s("sky-world", "Sky News", "https://feeds.skynews.com/feeds/rss/world.xml", "world"),
    _s("aljazeera", "Al Jazeera", "https://www.aljazeera.com/xml/rss/all.xml", "world"),
    _s("guardian-world", "The Guardian", "https://www.theguardian.com/world/rss", "world"),
    # India
    _s("bbc-india", "BBC News", "https://feeds.bbci.co.uk/news/world/asia/india/rss.xml", "india"),
    _s("ndtv", "NDTV", "https://feeds.feedburner.com/ndtvnews-top-stories", "india"),
    _s("thehindu", "The Hindu", "https://www.thehindu.com/news/national/feeder/default.rss", "india", metered=True),
    _s("toi", "Times of India", "https://timesofindia.indiatimes.com/rssfeedstopstories.cms", "india"),
    _s("indianexpress", "The Indian Express", "https://indianexpress.com/feed/", "india"),
    _s("livemint", "Mint", "https://www.livemint.com/rss/news", "india"),
    # Sports
    Source(
        "nfl-com", "NFL.com", "https://www.nfl.com/sitemap-fast-changing.xml", "sports", "nfl", headline_only=True, sitemap=True
    ),
    _s("espn-nfl", "ESPN", "https://www.espn.com/espn/rss/nfl/news", "sports", "nfl"),
    _s("cricinfo", "ESPNcricinfo", "https://www.espncricinfo.com/rss/content/story/feeds/0.xml", "sports", "cricket"),
    _s("guardian-tennis", "The Guardian", "https://www.theguardian.com/sport/tennis/rss", "sports", "tennis"),
    # Technology
    _s("ars-gadgets", "Ars Technica", "https://feeds.arstechnica.com/arstechnica/gadgets", "tech", "gadgets"),
    _s("ars", "Ars Technica", "https://feeds.arstechnica.com/arstechnica/index", "tech"),
    _s("verge", "The Verge", "https://www.theverge.com/rss/index.xml", "tech"),
    _s("techcrunch", "TechCrunch", "https://techcrunch.com/feed/", "tech"),
    _s("engadget", "Engadget", "https://www.engadget.com/rss.xml", "tech", "gadgets"),
    _s("tomsguide", "Tom's Guide", "https://www.tomsguide.com/feeds.xml", "tech", "gadgets"),
    _s("slashgear", "SlashGear", "https://www.slashgear.com/feed/", "tech", "gadgets"),
    _s("gizmodo", "Gizmodo", "https://gizmodo.com/feed", "tech"),
    _s("9to5mac", "9to5Mac", "https://9to5mac.com/feed/", "tech"),
    _s("tomshw", "Tom's Hardware", "https://www.tomshardware.com/feeds.xml", "tech"),
    _s("register", "The Register", "https://www.theregister.com/headlines.atom", "tech"),
    _s("bbc-tech", "BBC News", "https://feeds.bbci.co.uk/news/technology/rss.xml", "tech"),
    # Business
    _s("marketwatch", "MarketWatch", "https://feeds.content.dowjones.io/public/rss/mw_topstories", "business"),
    _s("cnbc-finance", "CNBC", "https://www.cnbc.com/id/10000664/device/rss/rss.html", "business", "markets"),
    _s("cnbc-investing", "CNBC", "https://www.cnbc.com/id/15839069/device/rss/rss.html", "business", "markets"),
    _s("cnbc", "CNBC", "https://www.cnbc.com/id/100003114/device/rss/rss.html", "business"),
    _s("et", "Economic Times", "https://economictimes.indiatimes.com/rssfeedstopstories.cms", "business"),
    _s("bbc-business", "BBC News", "https://feeds.bbci.co.uk/news/business/rss.xml", "business"),
    _s("guardian-business", "The Guardian", "https://www.theguardian.com/uk/business/rss", "business"),
    _s(
        "nyt-business",
        "The New York Times",
        "https://rss.nytimes.com/services/xml/rss/nyt/Business.xml",
        "business",
        metered=True,
    ),
)
