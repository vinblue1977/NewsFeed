import type { ComponentChildren } from 'preact';
import { useEffect, useMemo, useRef, useState } from 'preact/hooks';

import { loadArticles, loadFeed, loadWeather } from './api';
import { type Block, groupBlocks, readingMinutes } from './article';
import { badgeColor, BRIEF_TOP_COLOR, briefing, coverage, initial, isStale, parseRoute, readerPage, safeUrl, stories, storyLink, storyPage, timeAgo, TOPICS, topicLabel, topStory } from './feed';
import type { Story } from './feed';
import type { Feed, Topic } from './types';
import { degrees, describe, isFresh, type Weather } from './weather';

const PAGE = 30;
const TICK_MS = 60_000;
const COVERAGE_SHOWN = 8;
const EXTERNAL = { target: '_blank', rel: 'noopener noreferrer' } as const;
const VIEW_KEY = 'news.view';

type View = 'feed' | 'brief';

function savedView(): View {
  try {
    return localStorage.getItem(VIEW_KEY) === 'brief' ? 'brief' : 'feed';
  } catch {
    return 'feed';  // storage can be blocked; the app works without it
  }
}

function saveView(view: View): void {
  try {
    localStorage.setItem(VIEW_KEY, view);
  } catch {
    /* not remembered; fine */
  }
}

type Load = { state: 'loading' } | { state: 'error' } | { state: 'ready'; feed: Feed };

function WeatherStrip({ weather, stale }: { weather: Weather; stale: boolean }) {
  if (stale) {  // never present an old forecast or its alerts as current
    return (
      <section class="wx" aria-label="Local weather">
        <div><div class="wx-k">LOCAL WEATHER</div><div class="wx-sub">Forecast is out of date. Check the National Weather Service for alerts.</div></div>
      </section>
    );
  }
  const { label, icon } = describe(weather.code, weather.isDay);
  const range = weather.high !== null && weather.low !== null ? ` · H ${degrees(weather.high)} L ${degrees(weather.low)}` : '';
  const alert = weather.alerts[0];
  return (
    <section class="wx" aria-label="Local weather">
      <div>
        <div class="wx-k">LOCAL WEATHER</div>
        <div>{icon} {label}{range}</div>
        {alert && <div class="wx-alert">⚠ {alert.event}{weather.alerts.length > 1 ? ` +${weather.alerts.length - 1}` : ''} · National Weather Service</div>}
        {!weather.alertsOk && <div class="wx-sub">Weather alerts unavailable</div>}
      </div>
      <b>{degrees(weather.temp)}</b>
    </section>
  );
}

/** A story link: the Story screen when several sources cover it, otherwise the Reader. */
function StoryAnchor({ story, class: cls, children }: { story: Story; class: string; children: ComponentChildren }) {
  return <a class={cls} href={storyLink(story)}>{children}</a>;
}

function readerNote(o: { source: string; hasSummary: boolean; hasLink: boolean; hasFullText: boolean }): string {
  const { source } = o;
  if (!o.hasLink) return `${source} did not supply a usable link to the story.`;
  if (o.hasFullText) return `Text supplied by ${source}. Open the original for images and the full page.`;
  return o.hasSummary
    ? `Showing the summary supplied by ${source}. Read the rest on their site.`
    : `${source} supplies only the headline. Read the story on their site.`;
}

function ArticleBody({ blocks }: { blocks: Block[] }) {
  return (
    <div class="body">
      {groupBlocks(blocks).map((g, n) => {
        if (g.kind === 'h') return <h2 key={n}>{g.text}</h2>;
        if (g.kind === 'q') return <blockquote key={n}>{g.text}</blockquote>;
        if (g.kind === 'list') return <ul key={n}>{g.items.map((x, k) => <li key={k}>{x}</li>)}</ul>;
        return <p key={n}>{g.text}</p>;
      })}
    </div>
  );
}

function ReaderScreen({ feed, id, now, canGoBack }: { feed: Feed; id: string; now: Date; canGoBack: boolean }) {
  const page = readerPage(feed, id);
  const wantsFull = page?.item.full === true;
  const [blocks, setBlocks] = useState<Block[] | undefined>();
  const [answered, setAnswered] = useState(false);  // the full-text request has finished (with or without this article)
  const fetching = wantsFull && !answered;  // so "Loading" shows exactly while waiting, and cannot hang
  useEffect(() => {
    if (!wantsFull) return undefined;
    let current = true;
    void loadArticles(id).then((articles) => {
      if (!current) return;
      const found = articles?.[id];
      setBlocks(Array.isArray(found) ? found : undefined);
      setAnswered(true);
    });
    return () => { current = false; };
  }, [wantsFull, id]);
  const minutes = useMemo(() => (blocks ? readingMinutes(blocks) : 0), [blocks]);
  const goBack = () => { if (canGoBack) history.back(); else location.hash = ''; };
  const url = page ? safeUrl(page.item.url) : '#';
  const canShare = typeof navigator.share === 'function' && url !== '#';
  return (
    <div class="wrap">
      <div class="back">
        <button type="button" class="ib" aria-label="Back" onClick={goBack}>‹</button>
        {page && canShare && (
          <button type="button" class="ib" aria-label="Share" onClick={() => { void navigator.share({ title: page.item.title, url }).catch(() => undefined); }}>↗</button>
        )}
      </div>
      {!page && <div class="empty"><b>Article not found</b><span>It may have dropped out of the latest news.</span></div>}
      {page && (
        <article class="art">
          <div class="tag">{topicLabel(page.item.topic)}{page.item.place ? ` · ${page.item.place}` : ''}</div>
          <h1>{page.item.title}</h1>
          <div class="src art-src">
            <span class="fav" style={{ background: badgeColor(page.item.source) }}>{initial(page.item.source)}</span>
            {page.item.source} · {timeAgo(page.item.published, now)}{blocks ? ` · ${minutes} min read` : ''}{page.item.metered ? ' · Metered' : ''}
          </div>
          {blocks ? <ArticleBody blocks={blocks} /> : page.item.summary ? <p>{page.item.summary}</p> : null}
          {fetching && !blocks && <p class="wait">Loading the full text…</p>}
          <div class="box infobox">
            <span aria-hidden="true">ⓘ</span>
            <span>{readerNote({ source: page.item.source, hasSummary: page.item.summary !== '', hasLink: url !== '#', hasFullText: blocks !== undefined })}</span>
          </div>
          <div class="btns">
            {url !== '#' && <a class="btn" href={url} {...EXTERNAL}>Open original ↗</a>}
            {page.coverageId && <a class="btn g" href={`#/story/${page.coverageId}`}>Full coverage</a>}
          </div>
          <div class="note">Paywalled articles are filtered out · sources that limit free reads are marked Metered</div>
        </article>
      )}
    </div>
  );
}

function StoryScreen({ feed, id, now, canGoBack }: { feed: Feed; id: string; now: Date; canGoBack: boolean }) {
  const page = storyPage(feed, id);
  const [all, setAll] = useState(false);
  const goBack = () => { if (canGoBack) history.back(); else location.hash = ''; };  // a deep link has nothing in the app to go back to
  const shown = page && !all ? page.items.slice(0, COVERAGE_SHOWN) : (page?.items ?? []);
  return (
    <div class="wrap">
      <div class="back"><button type="button" class="ib" aria-label="Back" onClick={goBack}>‹</button></div>
      {!page && <div class="empty"><b>Story not found</b><span>It may have dropped out of the latest news.</span></div>}
      {page && (
        <>
          <div class="tag">{topicLabel(page.cluster.topic)} · Full coverage</div>
          <h1 class="ttl">{page.cluster.title}</h1>
          <div class="meta">Updated {timeAgo(page.items[0]?.published ?? page.cluster.published, now)} · {page.sources} {page.sources === 1 ? 'source' : 'sources'}</div>
          <div class="sh"><b>Coverage from {page.sources} {page.sources === 1 ? 'source' : 'sources'}</b></div>
          {shown.map((i) => (
            <a class="cv" key={i.id} href={`#/read/${i.id}`}>
              <span class="fav" style={{ background: badgeColor(i.source) }}>{initial(i.source)}</span>
              <div class="cvt"><b>{i.title}</b><small>{i.source} · {timeAgo(i.published, now)}{i.metered ? ' · Metered' : ''}</small></div>
              <span class="chev" aria-hidden="true">›</span>
            </a>
          ))}
          {page.items.length > COVERAGE_SHOWN && !all && (
            <div class="more"><button type="button" class="btn g" onClick={() => setAll(true)}>Show {page.items.length - COVERAGE_SHOWN} more</button></div>
          )}
          <div class="note">Paywalled articles are filtered out · sources that limit free reads are marked Metered</div>
          {page.related.length > 0 && (
            <>
              <div class="sh"><b>Related</b></div>
              {page.related.map((r) => (
                <StoryAnchor story={r} key={r.item.id} class="row">
                  <div class="t">
                    <Source name={r.item.source} when={timeAgo(r.item.published, now)} />
                    <h3>{r.item.title}</h3>
                  </div>
                </StoryAnchor>
              ))}
            </>
          )}
        </>
      )}
    </div>
  );
}

function TabBar() {
  return (
    <nav class="tabbar" aria-label="Sections">
      <a class="on" href="#" aria-current="page">For you</a>
      {['Explore', 'Saved', 'Markets', 'Settings'].map((name) => (
        <button key={name} type="button" disabled>{name}</button>
      ))}
    </nav>
  );
}

function Source({ name, when, extra }: { name: string; when: string; extra?: string }) {
  return (
    <div class="src">
      <span class="fav" style={{ background: badgeColor(name) }}>{initial(name)}</span>
      {[name, when, extra].filter(Boolean).join(' · ')}
    </div>
  );
}

export function App() {
  const [load, setLoad] = useState<Load>({ state: 'loading' });
  const [topic, setTopic] = useState<Topic | 'all'>('all');
  const [view, setView] = useState<View>(savedView);
  const [shown, setShown] = useState(PAGE);
  const [now, setNow] = useState(() => new Date());
  const [weather, setWeather] = useState<Weather | undefined>();
  const [route, setRoute] = useState(() => parseRoute(location.hash));
  const homeScroll = useRef(0);
  const routeRef = useRef(route);
  const inAppNavs = useRef(0);  // hash changes since the app opened: more than zero means there is an app screen to go back to

  const latest = useRef(0);
  const refresh = () => {
    const mine = ++latest.current;  // a slower, older response must not overwrite a newer one
    void loadWeather().then((w) => { if (w) setWeather(w); });  // independent of the feed; a failed refresh keeps the last good one
    loadFeed().then(
      (feed) => { if (mine === latest.current) setLoad({ state: 'ready', feed }); },
      () => { if (mine === latest.current) setLoad((prev) => (prev.state === 'ready' ? prev : { state: 'error' })); },
    );
  };
  useEffect(() => {
    refresh();
    const onVisible = () => {
      if (document.visibilityState === 'visible') { setNow(new Date()); refresh(); }
    };
    document.addEventListener('visibilitychange', onVisible);
    const onHash = () => {
      const next = parseRoute(location.hash);
      if (routeRef.current.kind === 'home' && next.kind !== 'home') homeScroll.current = window.scrollY;  // come back to the same place
      routeRef.current = next;
      inAppNavs.current += 1;
      setRoute(next);
    };
    window.addEventListener('hashchange', onHash);
    const tick = setInterval(() => setNow(new Date()), TICK_MS);  // "x min ago" and the stale banner keep moving
    return () => {
      latest.current = -1;
      document.removeEventListener('visibilitychange', onVisible);
      window.removeEventListener('hashchange', onHash);
      clearInterval(tick);
    };
  }, []);

  const feed = load.state === 'ready' ? load.feed : undefined;
  const isBrief = view === 'brief';
  // only the visible view is computed
  const list = useMemo(() => (feed && !isBrief ? stories(feed, topic) : []), [feed, topic, isBrief]);
  const lead = useMemo(() => (feed && !isBrief ? topStory(list, now) : undefined), [feed, list, now, isBrief]);
  const full = useMemo(() => (feed && lead ? coverage(feed, lead) : []), [feed, lead]);
  const rest = list.filter((s) => s.item.id !== lead?.item.id);
  const brief = useMemo(() => (feed && isBrief ? briefing(feed, now) : undefined), [feed, now, isBrief]);
  const toggleView = () => {
    const next = isBrief ? 'feed' : 'brief';
    setView(next);
    saveView(next);
    setTopic('all');  // the Briefing covers everything, so a topic chosen earlier must not stay hidden behind it
    setShown(PAGE);
  };
  const weatherStale = weather ? !isFresh(weather.generated, now) : false;
  const screenKey = route.kind === 'home' ? 'home' : `${route.kind}:${route.id}`;
  useEffect(() => {
    window.scrollTo(0, screenKey === 'home' ? homeScroll.current : 0);
  }, [screenKey]);
  const date = now.toLocaleDateString('en-US', { weekday: 'long', month: 'short', day: 'numeric' });

  if (route.kind !== 'home') {
    return (
      <>
        {feed ? (
          route.kind === 'story'
            ? <StoryScreen key={route.id} feed={feed} id={route.id} now={now} canGoBack={inAppNavs.current > 0} />
            : <ReaderScreen key={route.id} feed={feed} id={route.id} now={now} canGoBack={inAppNavs.current > 0} />
        ) : (
          <div class="wrap">
            <div class="back"><a class="ib" href="#" aria-label="Home">‹</a></div>
            {load.state === 'error' ? (
              <div class="empty"><b>Can't load the news</b><span>Check your connection.</span>
                <button type="button" class="btn" onClick={() => { setLoad({ state: 'loading' }); refresh(); }}>Try again</button></div>
            ) : <p class="note">Loading…</p>}
          </div>
        )}
        <TabBar />
      </>
    );
  }

  return (
    <>
      <div class="wrap">
        <header class="hdr">
          <div>
            <div class="e">{date}{isBrief && brief ? ` · ${brief.total} stories` : ''}</div>
            <h1>{isBrief ? 'Briefing' : topic === 'all' ? 'For you' : topicLabel(topic)}</h1>
          </div>
          <button type="button" class={isBrief ? 'ib on' : 'ib'} aria-pressed={isBrief} aria-label="Briefing view" title="Briefing view"
            onClick={toggleView}>☰</button>
        </header>
        {!isBrief && (
          <nav class="chips" aria-label="Topics">
            {TOPICS.map((t) => (
              <button key={t.id} type="button" class={t.id === topic ? 'on' : ''} aria-pressed={t.id === topic}
                onClick={() => { setTopic(t.id); setShown(PAGE); }}>
                {t.label}
              </button>
            ))}
          </nav>
        )}

        {load.state === 'loading' && <p class="note">Loading the latest stories…</p>}
        {load.state === 'error' && (
          <div class="empty"><b>Can't load the news</b><span>Check your connection.</span>
            <button type="button" class="btn" onClick={() => { setLoad({ state: 'loading' }); refresh(); }}>Try again</button></div>
        )}
        {feed && isStale(feed.generated, now) && <p class="note warn">Updated {timeAgo(feed.generated, now)}; newer stories may be missing.</p>}
        {feed && isBrief && brief && brief.total === 0 && <div class="empty"><b>Nothing new today</b><span>No stories from the last 24 hours.</span></div>}
        {feed && !isBrief && list.length === 0 && <div class="empty"><b>Nothing here yet</b><span>No recent stories in this topic.</span></div>}

        {isBrief && brief && (
          <>
            {weather && <WeatherStrip weather={weather} stale={weatherStale} />}
            {brief.top && (
              <>
                <div class="grp"><i style={{ background: BRIEF_TOP_COLOR }} />Top story</div>
                <StoryAnchor story={brief.top} class="bi first">
                  <h2>{brief.top.item.title}</h2>
                  {brief.top.item.summary && <p>{brief.top.item.summary.slice(0, 200)}</p>}
                  <div class="m"><span>{brief.top.item.source}</span><span>{timeAgo(brief.top.item.published, now)}</span>
                    {brief.top.sources > 1 && <span class="c">{brief.top.sources} sources</span>}</div>
                </StoryAnchor>
              </>
            )}
            {brief.groups.map((g) => (
              <section key={g.label}>
                <div class="grp"><i style={{ background: g.color }} />{g.label}</div>
                {g.stories.map((st) => (
                  <StoryAnchor story={st} key={st.item.id} class="bi">
                    <h2>{st.item.title}</h2>
                    <div class="m"><span>{st.item.source}</span><span>{timeAgo(st.item.published, now)}</span></div>
                  </StoryAnchor>
                ))}
              </section>
            ))}
            {brief.total > 0 && <div class="done">You're all caught up ✓</div>}
          </>
        )}

        {!isBrief && lead && (
          <>
            <div class="sec"><b>Top story</b></div>
            <StoryAnchor story={lead} class="big">
              <Source name={lead.item.source} when={timeAgo(lead.item.published, now)} />
              <h2>{lead.item.title}</h2>
            </StoryAnchor>
            {full.length > 0 && (
              <div class="full">
                <div class="lab">FULL COVERAGE · {lead.sources} SOURCES</div>
                {full.map((i) => (
                  <a class="it" key={i.id} href={`#/read/${i.id}`}>
                    <Source name={i.source} when={timeAgo(i.published, now)} />
                    <b>{i.title}</b>
                  </a>
                ))}
              </div>
            )}
          </>
        )}

        {!isBrief && weather && <WeatherStrip weather={weather} stale={weatherStale} />}
        {!isBrief && rest.slice(0, shown).map((s) => (
          <StoryAnchor story={s} key={s.item.id} class="row">
            <div class="t">
              <Source name={s.item.source} when={timeAgo(s.item.published, now)}
                extra={[topicLabel(s.item.topic), s.item.place, s.sources > 1 ? `${s.sources} sources` : ''].filter(Boolean).join(' · ')} />
              <h3>{s.item.title}</h3>
            </div>
          </StoryAnchor>
        ))}
        {!isBrief && rest.length > shown && (
          <div class="more"><button type="button" class="btn g" onClick={() => setShown((n) => n + PAGE)}>Show more</button></div>
        )}
      </div>
      <TabBar />
    </>
  );
}
