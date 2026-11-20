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
    topic: str  # us | world | india | sports | tech | business | entertainment | science | local
    subtopic: str | None = None  # a Browse tile: sports, tech or business ids, e.g. nfl, gadgets, science, bollywood
    enabled: bool = True
    metered: bool = False
    headline_only: bool = False  # Google News `site:` feeds: title, source and link, no summary
    site: str | None = None  # Google News `site:` query: the publisher's domain when an item has no <source>
    trusted: bool = (
        False  # a Google News search already scoped to the places (not one limited to a publisher): skip the place filter
    )
    sitemap: bool = False  # the URL is a Google News sitemap (title, link, time), not RSS or Atom
    news_only: bool = False  # a Google News search of one site: keep only headline-like titles, not the site's page titles
    alert: bool = False  # an official alert feed: each new item is pushed (see ingest.push); items carry a private `_alert` flag
    only_matching: str | None = (
        None  # regex: keep an item only when its title or summary matches (a mixed feed narrowed to one theme)
    )


# Words that mark a South Indian film story: the industries and languages, the big studios and the best-known stars and
# directors. The Hindu's movie feed mixes Hindi, Hollywood and South news, so it is narrowed to what matches. Rough by
# design: a South story that names none of these is missed, which beats showing Bond news under South Cinema.
SOUTH_CINEMA = (
    r"(?<!\w)("
    r"tamil|telugu|kannada|malayalam|kollywood|tollywood|mollywood|sandalwood|south indian"
    r"|south film|pan-indian"
    r"|kerala|chennai|thiruvananthapuram|iffk|hombale|mythri"
    r"|sun pictures"
    r"|rajinikanth|kamal haasan|thalapathy|vijay sethupathi|ajith|suriya|dhanush|sivakarthikeyan|simbu"
    r"|jayam ravi|lokesh kanagaraj|mani ratnam"
    r"|allu arjun|prabhas|mahesh babu|ram charan|jr\.? ntr|chiranjeevi|nagarjuna|pawan kalyan"
    r"|ss rajamouli|rajamouli|vijay deverakonda"
    r"|mohanlal|mammootty|dulquer|fahadh|prithviraj|tovino|nivin pauly|jeethu joseph|amal neerad"
    r"|rishab shetty|shivarajkumar|kichcha sudeep|rashmika|nayanthara|samantha ruth prabhu"
    r"|sai pallavi|keerthy suresh|trisha krishnan|sreeleela|devi sri prasad"
    r")(?!\w)"
)


def _s(
    id: str,  # noqa: A002
    name: str,
    url: str,
    topic: str,
    subtopic: str | None = None,
    *,
    metered: bool = False,
    only_matching: str | None = None,
) -> Source:
    return Source(id, name, url, topic, subtopic, metered=metered, only_matching=only_matching)


SOURCES: tuple[Source, ...] = (
    # US
    _s("npr", "NPR", "https://feeds.npr.org/1001/rss.xml", "us"),
    _s("pbs", "PBS NewsHour", "https://www.pbs.org/newshour/feeds/rss/headlines", "us"),
    _s("abc", "ABC News", "https://abcnews.go.com/abcnews/topstories", "us"),
    _s("cbs", "CBS News", "https://www.cbsnews.com/latest/rss/main", "us"),
    _s("nbc", "NBC News", "https://feeds.nbcnews.com/nbcnews/public/news", "us"),
    _s("thehill", "The Hill", "https://thehill.com/feed/", "us"),
    _s("bbc-us", "BBC News", "https://feeds.bbci.co.uk/news/world/us_and_canada/rss.xml", "us"),
    _s("abc-us", "ABC News", "https://abcnews.go.com/abcnews/usheadlines", "us"),
    _s("nbc-us", "NBC News", "https://feeds.nbcnews.com/nbcnews/public/us-news", "us"),
    _s("washtimes", "The Washington Times", "https://www.washingtontimes.com/rss/headlines/news/", "us"),
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
    # Entertainment (Browse tiles only: bollywood, south, hollywood)
    _s("bollywoodhungama", "Bollywood Hungama", "https://www.bollywoodhungama.com/rss/news.xml", "entertainment", "bollywood"),
    _s(
        "ht-bollywood",
        "Hindustan Times",
        "https://www.hindustantimes.com/feeds/rss/entertainment/bollywood/rssfeed.xml",
        "entertainment",
        "bollywood",
    ),
    _s(
        "ie-bollywood",
        "The Indian Express",
        "https://indianexpress.com/section/entertainment/bollywood/feed/",
        "entertainment",
        "bollywood",
    ),
    _s(
        "toi-entertainment",
        "Times of India",
        "https://timesofindia.indiatimes.com/rssfeeds/1081479906.cms",
        "entertainment",
        "bollywood",
    ),
    _s(
        "ie-telugu",
        "The Indian Express",
        "https://indianexpress.com/section/entertainment/telugu/feed/",
        "entertainment",
        "south",
    ),
    _s("ie-tamil", "The Indian Express", "https://indianexpress.com/section/entertainment/tamil/feed/", "entertainment", "south"),
    _s(
        "ht-tamil",
        "Hindustan Times",
        "https://www.hindustantimes.com/feeds/rss/entertainment/tamil-cinema/rssfeed.xml",
        "entertainment",
        "south",
    ),
    _s(
        "ht-telugu",
        "Hindustan Times",
        "https://www.hindustantimes.com/feeds/rss/entertainment/telugu-cinema/rssfeed.xml",
        "entertainment",
        "south",
    ),
    _s(
        "thehindu-movies",
        "The Hindu",
        "https://www.thehindu.com/entertainment/movies/feeder/default.rss",
        "entertainment",
        "south",
        metered=True,
        only_matching=SOUTH_CINEMA,
    ),
    _s("variety", "Variety", "https://variety.com/feed/", "entertainment", "hollywood", metered=True),
    _s("thr", "The Hollywood Reporter", "https://www.hollywoodreporter.com/feed/", "entertainment", "hollywood", metered=True),
    _s("deadline", "Deadline", "https://deadline.com/feed/", "entertainment", "hollywood"),
    _s("guardian-film", "The Guardian", "https://www.theguardian.com/film/rss", "entertainment", "hollywood"),
    # Science (Browse tile only; listed before Technology so a story both feeds carry is filed as science)
    _s("nasa", "NASA", "https://www.nasa.gov/feed/", "science", "science"),
    _s("ars-science", "Ars Technica", "https://feeds.arstechnica.com/arstechnica/science", "science", "science"),
    _s("bbc-science", "BBC News", "https://feeds.bbci.co.uk/news/science_and_environment/rss.xml", "science", "science"),
    _s("guardian-science", "The Guardian", "https://www.theguardian.com/science/rss", "science", "science"),
    _s("npr-science", "NPR", "https://www.npr.org/rss/rss.php?id=1007", "science", "science"),
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
    # Linux, in the Technology tile too
    _s("9to5linux", "9to5Linux", "https://9to5linux.com/feed", "tech", "gadgets"),
    _s("phoronix", "Phoronix", "https://www.phoronix.com/rss.php", "tech", "gadgets"),
    _s("omgubuntu", "OMG! Ubuntu", "https://www.omgubuntu.co.uk/feed", "tech", "gadgets"),
    _s("itsfoss", "It's FOSS News", "https://news.itsfoss.com/feed/", "tech", "gadgets"),
    # Business
    _s("marketwatch", "MarketWatch", "https://feeds.content.dowjones.io/public/rss/mw_topstories", "business"),
    _s("cnbc-finance", "CNBC", "https://www.cnbc.com/id/10000664/device/rss/rss.html", "business", "markets"),
    _s("cnbc-investing", "CNBC", "https://www.cnbc.com/id/15839069/device/rss/rss.html", "business", "markets"),
    _s("cnbc", "CNBC", "https://www.cnbc.com/id/100003114/device/rss/rss.html", "business"),
    _s("et", "Economic Times", "https://economictimes.indiatimes.com/rssfeedstopstories.cms", "business"),
    _s("bbc-business", "BBC News", "https://feeds.bbci.co.uk/news/business/rss.xml", "business"),
    _s("guardian-business", "The Guardian", "https://www.theguardian.com/uk/business/rss", "business"),
)
