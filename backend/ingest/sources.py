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
    subtopic: str | None = None  # sports: nfl | cricket | tennis
    enabled: bool = True
    metered: bool = False


def _s(id: str, name: str, url: str, topic: str, subtopic: str | None = None, **kw: bool) -> Source:  # noqa: A002
    return Source(id, name, url, topic, subtopic, **kw)


SOURCES: tuple[Source, ...] = (
    # US
    _s("npr", "NPR", "https://feeds.npr.org/1001/rss.xml", "us"),
    _s("pbs", "PBS NewsHour", "https://www.pbs.org/newshour/feeds/rss/headlines", "us"),
    _s("abc", "ABC News", "https://abcnews.go.com/abcnews/topstories", "us"),
    _s("cbs", "CBS News", "https://www.cbsnews.com/latest/rss/main", "us"),
    _s("nbc", "NBC News", "https://feeds.nbcnews.com/nbcnews/public/news", "us"),
    _s("thehill", "The Hill", "https://thehill.com/feed/", "us"),
    _s("bbc-us", "BBC News", "https://feeds.bbci.co.uk/news/world/us_and_canada/rss.xml", "us"),
    # World
    _s("bbc-world", "BBC News", "https://feeds.bbci.co.uk/news/world/rss.xml", "world"),
    _s("aljazeera", "Al Jazeera", "https://www.aljazeera.com/xml/rss/all.xml", "world"),
    _s("guardian-world", "The Guardian", "https://www.theguardian.com/world/rss", "world"),
    # India
    _s("bbc-india", "BBC News", "https://feeds.bbci.co.uk/news/world/asia/india/rss.xml", "india"),
    _s("ndtv", "NDTV", "https://feeds.feedburner.com/ndtvnews-top-stories", "india"),
    _s("thehindu", "The Hindu", "https://www.thehindu.com/news/national/feeder/default.rss", "india", metered=True),
    _s("toi", "Times of India", "https://timesofindia.indiatimes.com/rssfeedstopstories.cms", "india"),
    # Sports
    _s("espn-nfl", "ESPN", "https://www.espn.com/espn/rss/nfl/news", "sports", "nfl"),
    _s("cricinfo", "ESPNcricinfo", "https://www.espncricinfo.com/rss/content/story/feeds/0.xml", "sports", "cricket"),
    _s("bbc-tennis", "BBC Sport", "https://feeds.bbci.co.uk/sport/tennis/rss.xml", "sports", "tennis"),
    # Technology
    _s("ars", "Ars Technica", "https://feeds.arstechnica.com/arstechnica/index", "tech"),
    _s("verge", "The Verge", "https://www.theverge.com/rss/index.xml", "tech"),
    _s("techcrunch", "TechCrunch", "https://techcrunch.com/feed/", "tech"),
    _s("engadget", "Engadget", "https://www.engadget.com/rss.xml", "tech"),
    _s("9to5mac", "9to5Mac", "https://9to5mac.com/feed/", "tech"),
    _s("tomshw", "Tom's Hardware", "https://www.tomshardware.com/feeds/all", "tech"),
    _s("register", "The Register", "https://www.theregister.com/headlines.atom", "tech"),
    _s("bbc-tech", "BBC News", "https://feeds.bbci.co.uk/news/technology/rss.xml", "tech"),
    # Business
    _s("marketwatch", "MarketWatch", "https://feeds.content.dowjones.io/public/rss/mw_topstories", "business"),
    _s("cnbc", "CNBC", "https://www.cnbc.com/id/100003114/device/rss/rss.html", "business"),
    _s("et", "Economic Times", "https://economictimes.indiatimes.com/rssfeedstopstories.cms", "business"),
)
