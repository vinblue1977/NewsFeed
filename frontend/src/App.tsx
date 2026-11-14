import type { ComponentChildren } from 'preact';
import { useEffect, useMemo, useRef, useState } from 'preact/hooks';

import { loadArticles, loadFeed, loadWatchlist, loadWeather, watchlistSymbols } from './api';
import { type Block, groupBlocks, readingMinutes } from './article';
import { useChrome } from './chrome';
import { badgeColor, BRIEF_TOP_COLOR, briefing, coverage, imageSrc, initial, isStale, parseRoute, readerPage, safeUrl, sections, stories, storyLink, storyPage, timeAgo, TOPICS, topicLabel, topStory } from './feed';
import type { Section, Story } from './feed';
import { dayRange, formatMove, historyChange, isFresh as marketsFresh, isMarketNews, type Markets, priceLabel, type Quote, sparkline, watchTerms } from './markets';
import { usePullToRefresh } from './pull';
import { loadSettings, readSize, saveSettings, type Settings, shownCount, sourceNames, TEXT_SIZES, toggled, WATCH_KEY, withoutSources } from './settings';
import type { Feed, Item, Topic } from './types';
import { degrees, describe, isFresh, type Weather } from './weather';

const needsMarkets = (kind: string) => kind === 'markets' || kind === 'settings' || kind === 'quote';
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

/** A story's picture; nothing at all if it has none or it fails to load, so a broken image never shows. */
function Pic({ item, class: cls, onFail }: { item: Item; class: string; onFail?: () => void }) {
  const src = imageSrc(item);
  const [failed, setFailed] = useState<string | undefined>();  // which picture failed, so a new story's picture still gets its chance
  if (!src || failed === src) return null;
  return <img class={cls} src={src} alt="" loading="lazy" decoding="async" onError={() => { setFailed(src); onFail?.(); }} />;
}

/** One story in a list: text, with a small picture beside it when there is one. */
function StoryRow({ s, now }: { s: Story; now: Date }) {
  const [broken, setBroken] = useState<string | undefined>();  // the picture that failed to load: then the row is text only
  const hasImg = imageSrc(s.item) !== undefined && broken !== imageSrc(s.item);
  return (
    <StoryAnchor story={s} class={hasImg ? 'row has-img' : 'row'}>
      <div class="t">
        <Source name={s.item.source} when={timeAgo(s.item.published, now)}
          extra={[topicLabel(s.item.topic), s.sources > 1 ? `${s.sources} sources` : ''].filter(Boolean).join(' · ')} />
        <h3>{s.item.title}</h3>
      </div>
      <Pic item={s.item} class="thumb" onFail={() => setBroken(imageSrc(s.item))} />
    </StoryAnchor>
  );
}

function TopicSection({ section, now, onAll }: { section: Section; now: Date; onAll: () => void }) {
  const { lead } = section;
  return (
    <section aria-label={section.label}>
      <div class="grp sech"><i style={{ background: section.color }} />{section.label}
        <button type="button" class="all" onClick={onAll}>See all {section.total} ›</button></div>
      <StoryAnchor story={lead} class="lead">
        <Pic item={lead.item} class="pic" />
        <Source name={lead.item.source} when={timeAgo(lead.item.published, now)} />
        <h2>{lead.item.title}</h2>
      </StoryAnchor>
      {section.more.map((s) => <StoryRow key={s.item.id} s={s} now={now} />)}
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

function ReaderScreen({ feed, id, now, canGoBack, chromeHidden }: { feed: Feed; id: string; now: Date; canGoBack: boolean; chromeHidden: boolean }) {
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
      <div class={chromeHidden ? 'back hide' : 'back'}>
        <button type="button" class="ib" aria-label="Back" onClick={goBack}>‹</button>
        {page && canShare && (
          <button type="button" class="ib" aria-label="Share" onClick={() => { void navigator.share({ title: page.item.title, url }).catch(() => undefined); }}>↗</button>
        )}
      </div>
      {!page && <div class="empty"><b>Article not found</b><span>It may have dropped out of the latest news.</span></div>}
      {page && (
        <article class="art">
          <div class="tag">{topicLabel(page.item.topic)}</div>
          <h1>{page.item.title}</h1>
          <Pic item={page.item} class="pic" />
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

function StoryScreen({ feed, id, now, canGoBack, chromeHidden }: { feed: Feed; id: string; now: Date; canGoBack: boolean; chromeHidden: boolean }) {
  const page = storyPage(feed, id);
  const [all, setAll] = useState(false);
  const goBack = () => { if (canGoBack) history.back(); else location.hash = ''; };  // a deep link has nothing in the app to go back to
  const shown = page && !all ? page.items.slice(0, COVERAGE_SHOWN) : (page?.items ?? []);
  return (
    <div class="wrap">
      <div class={chromeHidden ? 'back hide' : 'back'}><button type="button" class="ib" aria-label="Back" onClick={goBack}>‹</button></div>
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

function PullIndicator({ distance, spinning }: { distance: number; spinning: boolean }) {
  if (distance === 0 && !spinning) return null;
  return (
    <div class={spinning ? 'pull spin' : 'pull'} style={{ transform: `translateY(${spinning ? 36 : distance * 0.6}px)`, opacity: spinning ? 1 : Math.min(1, distance / 70) }}
      role="status" aria-label={spinning ? 'Refreshing' : 'Pull to refresh'}>
      <span aria-hidden="true">{spinning ? '↻' : distance >= 70 ? '↑' : '↓'}</span>
    </div>
  );
}

function TabBar({ hidden = false, current = 'home' }: { hidden?: boolean; current?: 'home' | 'markets' | 'settings' }) {
  const link = (tab: 'home' | 'markets' | 'settings', href: string, label: string) =>
    current === tab ? <a class="on" href={href} aria-current="page">{label}</a> : <a href={href}>{label}</a>;
  return (
    <nav class={hidden ? 'tabbar hide' : 'tabbar'} aria-label="Sections">
      {link('home', '#', 'For you')}
      {['Explore', 'Saved'].map((name) => <button key={name} type="button" disabled>{name}</button>)}
      {link('markets', '#/markets', 'Markets')}
      {link('settings', '#/settings', 'Settings')}
    </nav>
  );
}

function QuoteRow({ q, index = false }: { q: Quote; index?: boolean }) {
  const { text, dir } = formatMove(q.change, q.changePct, q.currency);
  const points = sparkline(q.series);
  return (
    <li>
      <a class="q" href={`#/quote/${encodeURIComponent(q.symbol)}`}>
        <div class="qn"><b>{q.name}</b><span>{q.symbol.replace('^', '')}</span></div>
        {points && (
          <svg class={`qs ${dir}`} viewBox="0 0 100 28" preserveAspectRatio="none" aria-hidden="true">
            <polyline points={points} fill="none" stroke="currentColor" stroke-width="1.6" vector-effect="non-scaling-stroke" />
          </svg>
        )}
        <div class="qp"><b>{priceLabel(q.price, q.currency, index)}</b><span class={`chg ${dir}`}>{text}</span></div>
      </a>
    </li>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return value ? <li><span>{label}</span><b>{value}</b></li> : null;
}

/** One watchlist symbol: today's numbers and the 3-month graph. */
function QuoteScreen({ markets, loaded, symbol, now, canGoBack }: { markets: Markets | undefined; loaded: boolean; symbol: string; now: Date; canGoBack: boolean }) {
  const q = markets?.tickers.find((t) => t.symbol === symbol);
  const goBack = () => { if (canGoBack) history.back(); else location.hash = '#/markets'; };
  const move = q ? formatMove(q.change, q.changePct, q.currency) : undefined;
  const trend = q ? historyChange(q.history) : undefined;
  const trendMove = trend && q ? formatMove(trend.change, trend.pct, q.currency) : undefined;
  const points = q ? sparkline(q.history, 300, 120) : '';
  const lo = q && q.history.length > 1 ? Math.min(...q.history) : undefined;
  const hi = q && q.history.length > 1 ? Math.max(...q.history) : undefined;
  return (
    <div class="wrap">
      <div class="back"><button type="button" class="ib" aria-label="Back" onClick={goBack}>‹</button></div>
      <header class="hdr"><div><div class="e">{symbol}</div><h1>{q?.name ?? symbol}</h1></div></header>
      {!q && <p class="note">{markets || loaded ? 'No quote for this symbol right now.' : 'Loading…'}</p>}
      {q && move && (
        <>
          <div class="big"><b>{priceLabel(q.price, q.currency, false)}</b><span class={`chg ${move.dir}`}>{move.text}</span></div>
          <div class="grp">3 months</div>
          {points ? (
            <div class="card gr">
              <svg class={`qs ${trendMove?.dir ?? 'flat'}`} viewBox="0 0 300 120" preserveAspectRatio="none" role="img"
                aria-label={`Price over the last three months${trendMove ? `, ${trendMove.text}` : ''}`}>
                <polyline points={points} fill="none" stroke="currentColor" stroke-width="2" vector-effect="non-scaling-stroke" />
              </svg>
              <div class="gl"><span>Low {lo !== undefined ? priceLabel(lo, q.currency, false) : ''}</span><span>High {hi !== undefined ? priceLabel(hi, q.currency, false) : ''}</span></div>
              {trendMove && <div class={`chg ${trendMove.dir}`}>{trendMove.text} over 3 months</div>}
            </div>
          ) : <p class="note">The 3-month history is not available right now.</p>}
          <div class="grp">Today</div>
          <ul class="set stats">
            <Stat label="Previous close" value={q.prevClose !== null ? priceLabel(q.prevClose, q.currency, false) : ''} />
            <Stat label="Open" value={q.dayOpen !== null ? priceLabel(q.dayOpen, q.currency, false) : ''} />
            <Stat label="Day range" value={dayRange(q.dayLow, q.dayHigh, q.currency)} />
            <Stat label="Last trade" value={q.lastTrade ? timeAgo(q.lastTrade, now) : ''} />
          </ul>
          <p class="fine">Delayed, unofficial data from Yahoo Finance. Not investment advice.</p>
        </>
      )}
    </div>
  );
}

function MarketsScreen({ markets, hasKey, loaded, now, hidden, feed, onAllBusiness }: {
  markets: Markets | undefined; hasKey: boolean; loaded: boolean; now: Date; hidden: string[]; feed: Feed | undefined; onAllBusiness: () => void;
}) {
  const tickers = markets ? markets.tickers.filter((q) => !hidden.includes(q.symbol)) : [];
  const stale = markets ? !marketsFresh(markets.generated, now) : false;
  const open = markets && !stale ? tickers.some((q) => q.open) : false;  // `open` is frozen at build time
  const traded = tickers.find((q) => q.lastTrade)?.lastTrade;
  const news = useMemo(() => {
    if (!feed) return [];
    const top = topStory(stories(feed, 'all'), now);  // the For You top story is not repeated here
    const terms = watchTerms(markets?.tickers ?? []);
    return stories(feed, 'business').filter((s) => s.item.id !== top?.item.id && isMarketNews(s.item, terms)).slice(0, 5);
  }, [feed, now, markets]);
  return (
    <div class="wrap">
      <header class="hdr">
        <div>
          <div class="e">{tickers.length > 0 ? (open ? 'Market open' : 'Market closed') : 'Markets'}</div>
          <h1>Markets</h1>
        </div>
      </header>
      {!hasKey && <p class="note">Your watchlist is private. Add your key and symbols in Settings.</p>}
      {hasKey && !markets && !loaded && <p class="note">Loading quotes…</p>}
      {hasKey && !markets && loaded && <p class="note">No watchlist quotes yet. Add symbols in Settings; they appear within a few minutes.</p>}
      {markets && stale && <p class="note warn">Updated {timeAgo(markets.generated, now)}; prices may be out of date.</p>}
      {tickers.length > 0 && (
        <>
          <div class="grp">Watchlist</div>
          <ul class="ql">{tickers.map((q) => <QuoteRow key={q.symbol} q={q} />)}</ul>
        </>
      )}
      {markets && markets.missing > 0 && <p class="note">{markets.missing} {markets.missing === 1 ? 'quote is' : 'quotes are'} unavailable right now.</p>}
      {tickers.length > 0 && (
        <p class="fine">
          {traded ? `Last trade ${timeAgo(traded, now)}. ` : ''}Delayed, unofficial data from Yahoo Finance. Not investment advice.
        </p>
      )}
      {news.length > 0 && (
        <>
          <div class="grp">Market news</div>
          {news.map((s) => <StoryRow key={s.item.id} s={s} now={now} />)}
          <div class="btns"><button type="button" class="btn g" onClick={onAllBusiness}>All Business ›</button></div>
        </>
      )}
    </div>
  );
}

function WatchlistEditor({ watchKey, update, onSaved }: { watchKey: string; update: (next: Partial<Settings>) => void; onSaved: (key: string) => void }) {
  const [key, setKey] = useState(watchKey);
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState('');
  const keyOk = WATCH_KEY.test(key);
  const parse = () => text.split(/[\s,]+/).filter(Boolean);
  const run = async (symbols?: string[]) => {
    setBusy(true);
    setMsg('');
    const saved = await watchlistSymbols(key, symbols);
    setBusy(false);
    if (!saved) { setMsg('Could not reach the watchlist. Check the key and the symbols.'); return; }
    update({ watchKey: key });
    setText(saved.join(' '));
    onSaved(key);  // the quotes for this key (and, after a save, the fresh ones)
    if (symbols) setMsg('Saved. Quotes appear within a minute.'); else setMsg(`${saved.length} symbols loaded.`);
  };
  return (
    <details class="card fold">
      <summary>Edit watchlist symbols</summary>
      <label class="fld">Key
        <input type="password" autocomplete="off" autocapitalize="none" spellcheck={false} value={key}
          onInput={(e) => setKey((e.target as HTMLInputElement).value.trim())} />
      </label>
      <label class="fld">Symbols (spaces or commas)
        <textarea rows={3} autocapitalize="characters" spellcheck={false} value={text}
          onInput={(e) => setText((e.target as HTMLTextAreaElement).value)} />
      </label>
      <div class="btns">
        <button type="button" class="btn g" disabled={!keyOk || busy} onClick={() => void run()}>Load saved</button>
        <button type="button" class="btn" disabled={!keyOk || busy} onClick={() => void run(parse())}>Save</button>
      </div>
      {msg && <p class="note" role="status">{msg}</p>}
    </details>
  );
}

function SettingsScreen({ settings, update, sources, markets, marketsLoaded, onSaved }: {
  settings: Settings; update: (next: Partial<Settings>) => void; sources: string[]; markets: Markets | undefined; marketsLoaded: boolean;
  onSaved: (key: string) => void;
}) {
  const symbols = [...new Map([...(markets?.tickers ?? []).map((q) => [q.symbol, `${q.name} · ${q.symbol}`] as const),
    ...settings.hiddenTickers.map((t) => [t, t] as const)]).entries()];  // a hidden symbol no longer in the list can still be switched back on
  return (
    <div class="wrap">
      <header class="hdr"><div><div class="e">On this device</div><h1>Settings</h1></div></header>
      <div class="grp">Reader text size</div>
      <div class="seg" role="group" aria-label="Reader text size">
        {TEXT_SIZES.map((t) => (
          <button key={t.id} type="button" class={t.id === settings.textSize ? 'on' : ''} aria-pressed={t.id === settings.textSize}
            onClick={() => update({ textSize: t.id })}>{t.label}</button>
        ))}
      </div>
      <p class="sample">Sample of how an article will read.</p>
      <div class="grp">News sources</div>
      {sources.length === 0 && <p class="note">Sources appear once the news has loaded.</p>}
      {sources.length > 0 && (
        <details class="card fold">
          <summary>Choose sources ({sources.length - settings.hiddenSources.filter((h) => sources.includes(h)).length} of {sources.length} shown)</summary>
          <ul class="set inner">
            {sources.map((name) => (
              <li key={name}><label>{name}
                <input type="checkbox" checked={!settings.hiddenSources.includes(name)}
                  onChange={() => update({ hiddenSources: toggled(settings.hiddenSources, name) })} />
              </label></li>
            ))}
          </ul>
        </details>
      )}
      <div class="grp">Markets watchlist</div>
      <WatchlistEditor watchKey={settings.watchKey} update={update} onSaved={onSaved} />
      {symbols.length === 0 && <p class="note">{!settings.watchKey ? 'Add your key above to see your watchlist.' : markets ? 'No symbols yet.' : marketsLoaded ? 'Watchlist unavailable right now.' : 'Loading the watchlist…'}</p>}
      {symbols.length > 0 && (
        <details class="card fold">
          <summary>Show or hide symbols ({shownCount(symbols.map(([s]) => s), settings.hiddenTickers)} of {symbols.length} shown)</summary>
          <ul class="set inner">
            {symbols.map(([symbol, label]) => (
              <li key={symbol}><label>{label}
                <input type="checkbox" checked={!settings.hiddenTickers.includes(symbol)}
                  onChange={() => update({ hiddenTickers: toggled(settings.hiddenTickers, symbol) })} />
              </label></li>
            ))}
          </ul>
        </details>
      )}
      <p class="fine">Saved on this device only. Hiding a source or symbol does not delete it. The symbol list itself is kept privately on the server.</p>
    </div>
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
  const [markets, setMarkets] = useState<Markets | undefined>();
  const [marketsLoaded, setMarketsLoaded] = useState(false);
  const [settings, setSettings] = useState<Settings>(() => {
    const s = loadSettings();
    document.documentElement.style.setProperty('--read-size', `${readSize(s.textSize)}px`);  // before the first paint, so no reflow
    return s;
  });
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
  const settingsRef = useRef(settings);
  settingsRef.current = settings;
  const timers = useRef<number[]>([]);
  const afterSave = (key: string) => {  // the refresh runs in the background: look again a few times
    timers.current.forEach(clearTimeout);
    timers.current = [0, 5000, 15000, 40000].map((ms) => window.setTimeout(() => refreshMarkets(key), ms));
  };
  const latestMarkets = useRef(0);
  const refreshMarkets = (keyNow?: string) => {
    const mine = ++latestMarkets.current;  // a slower, older response must not overwrite a newer one
    const key = keyNow ?? settingsRef.current.watchKey;
    if (!key) { setMarkets(undefined); setMarketsLoaded(true); return; }
    void loadWatchlist(key).then((m) => {
      if (mine !== latestMarkets.current) return;
      if (m) setMarkets(m);  // a failed refresh keeps the last good quotes
      else if (keyNow !== undefined) setMarkets(undefined);  // ...but never another key's quotes
      setMarketsLoaded(true);
    });
  };
  useEffect(() => {
    refresh();
    if (needsMarkets(routeRef.current.kind)) refreshMarkets();
    const onVisible = () => {
      if (document.visibilityState === 'visible') {
        setNow(new Date());
        refresh();
        if (needsMarkets(routeRef.current.kind)) refreshMarkets();
      }
    };
    document.addEventListener('visibilitychange', onVisible);
    const onHash = () => {
      const next = parseRoute(location.hash);
      if (routeRef.current.kind === 'home' && next.kind !== 'home') homeScroll.current = window.scrollY;  // come back to the same place
      if (needsMarkets(next.kind)) refreshMarkets();
      routeRef.current = next;
      inAppNavs.current += 1;
      setRoute(next);
    };
    window.addEventListener('hashchange', onHash);
    const quotes = setInterval(() => {  // quotes move every 5 minutes in market hours
      if (document.visibilityState === 'visible' && routeRef.current.kind === 'markets') refreshMarkets();
    }, 5 * 60 * 1000);
    const tick = setInterval(() => setNow(new Date()), TICK_MS);  // "x min ago" and the stale banner keep moving
    return () => {
      latest.current = -1;
      document.removeEventListener('visibilitychange', onVisible);
      window.removeEventListener('hashchange', onHash);
      clearInterval(tick);
      clearInterval(quotes);
      timers.current.forEach(clearTimeout);
    };
  }, []);

  const raw = load.state === 'ready' ? load.feed : undefined;  // the Reader opens any article, even from a hidden source
  const feed = useMemo(() => (raw ? withoutSources(raw, settings.hiddenSources) : undefined), [raw, settings.hiddenSources]);
  const sources = useMemo(() => sourceNames(raw, settings.hiddenSources), [raw, settings.hiddenSources]);
  const update = (next: Partial<Settings>) => {
    setSettings((prev) => {  // from the latest state, so two quick taps both count
      const merged = { ...prev, ...next };
      saveSettings(merged);
      settingsRef.current = merged;
      return merged;
    });
  };
  useEffect(() => {
    document.documentElement.style.setProperty('--read-size', `${readSize(settings.textSize)}px`);
  }, [settings.textSize]);
  const isBrief = view === 'brief';
  // only the visible view is computed
  const list = useMemo(() => (feed && !isBrief ? stories(feed, topic) : []), [feed, topic, isBrief]);
  const lead = useMemo(() => (feed && !isBrief ? topStory(list, now) : undefined), [feed, list, now, isBrief]);
  const full = useMemo(() => (feed && lead ? coverage(feed, lead) : []), [feed, lead]);
  const rest = list.filter((s) => s.item.id !== lead?.item.id);
  const grouped = useMemo(() => (topic === 'all' && !isBrief ? sections(list, lead) : []), [list, lead, topic, isBrief]);
  const brief = useMemo(() => (feed && isBrief ? briefing(feed, now) : undefined), [feed, now, isBrief]);
  const toggleView = () => {
    const next = isBrief ? 'feed' : 'brief';
    setView(next);
    saveView(next);
    setTopic('all');  // the Briefing covers everything, so a topic chosen earlier must not stay hidden behind it
    setShown(PAGE);
  };
  const weatherStale = weather ? !isFresh(weather.generated, now) : false;
  const screenKey = route.kind === 'home' || route.kind === 'markets' || route.kind === 'settings' ? route.kind : `${route.kind}:${route.id}`;
  useEffect(() => {
    window.scrollTo(0, screenKey === 'home' ? homeScroll.current : 0);
  }, [screenKey]);
  const pull = usePullToRefresh(route.kind === 'home' || route.kind === 'markets', () => {
    setNow(new Date());
    if (routeRef.current.kind === 'markets') refreshMarkets();
    else refresh();
  });
  const chrome = useChrome(route.kind === 'story' || route.kind === 'read', screenKey);
  const date = now.toLocaleDateString('en-US', { weekday: 'long', month: 'short', day: 'numeric' });

  if (route.kind === 'markets') {
    return (
      <>
        <PullIndicator {...pull} />
        <MarketsScreen markets={markets} hasKey={settings.watchKey !== ''} loaded={marketsLoaded} now={now} hidden={settings.hiddenTickers}
          feed={feed} onAllBusiness={() => { setTopic('business'); setView('feed'); location.hash = '#'; }} />
        <TabBar current="markets" />
      </>
    );
  }

  if (route.kind === 'quote') {
    return (
      <>
        <QuoteScreen key={route.id} markets={markets} loaded={marketsLoaded} symbol={route.id} now={now} canGoBack={inAppNavs.current > 0} />
        <TabBar current="markets" />
      </>
    );
  }

  if (route.kind === 'settings') {
    return (
      <>
        <SettingsScreen settings={settings} update={update} sources={sources} markets={markets} marketsLoaded={marketsLoaded}
          onSaved={(key) => afterSave(key)} />
        <TabBar current="settings" />
      </>
    );
  }

  if (route.kind !== 'home') {
    return (
      <>
        {feed ? (
          route.kind === 'story'
            ? <StoryScreen key={route.id} feed={raw ?? feed} id={route.id} now={now} canGoBack={inAppNavs.current > 0} chromeHidden={chrome.hidden} />
            : <ReaderScreen key={route.id} feed={raw ?? feed} id={route.id} now={now} canGoBack={inAppNavs.current > 0} chromeHidden={chrome.hidden} />
        ) : (
          <div class="wrap">
            <div class="back"><a class="ib" href="#" aria-label="Home">‹</a></div>
            {load.state === 'error' ? (
              <div class="empty"><b>Can't load the news</b><span>Check your connection.</span>
                <button type="button" class="btn" onClick={() => { setLoad({ state: 'loading' }); refresh(); }}>Try again</button></div>
            ) : <p class="note">Loading…</p>}
          </div>
        )}
        {feed && <div class="prog" aria-hidden="true" />}
        {chrome.hidden && (
          <>
            <button type="button" class="zone top" aria-label="Show the top bar" onClick={chrome.show} />
            <button type="button" class="zone bottom" aria-label="Show the tab bar" onClick={chrome.show} />
          </>
        )}
        <TabBar hidden={chrome.hidden} />
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
        {raw && feed && raw.items.length > 0 && feed.items.length === 0 && <div class="empty"><b>All sources are hidden</b><span>Turn some back on in Settings.</span><a class="btn" href="#/settings">Open Settings</a></div>}
        {feed && !isBrief && list.length === 0 && feed.items.length > 0 && <div class="empty"><b>Nothing here yet</b><span>No recent stories in this topic.</span></div>}
        {feed && !isBrief && list.length === 0 && raw?.items.length === 0 && <div class="empty"><b>Nothing here yet</b><span>No recent stories in this topic.</span></div>}

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
              <Pic item={lead.item} class="pic" />
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
        {!isBrief && topic === 'all' && grouped.map((g) => (
          <TopicSection key={g.topic} section={g} now={now} onAll={() => { setTopic(g.topic); setShown(PAGE); window.scrollTo(0, 0); }} />
        ))}
        {!isBrief && topic !== 'all' && rest.slice(0, shown).map((s) => <StoryRow key={s.item.id} s={s} now={now} />)}
        {!isBrief && topic !== 'all' && rest.length > shown && (
          <div class="more"><button type="button" class="btn g" onClick={() => setShown((n) => n + PAGE)}>Show more</button></div>
        )}
      </div>
      <PullIndicator {...pull} />
      <TabBar />
    </>
  );
}
