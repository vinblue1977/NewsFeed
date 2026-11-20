import { Fragment, type ComponentChildren } from 'preact';
import { useEffect, useMemo, useRef, useState } from 'preact/hooks';

import { loadArticles, loadEarnings, loadFeed, loadKernel, loadOnThisDay, loadSchedule, loadScores, loadWatchlist, loadWeather, watchlistSymbols } from './api';
import { type Block, groupBlocks, readingMinutes } from './article';
import { useChrome } from './chrome';
import { type Kernel, kernelFresh, kernelTitle } from './kernel';
import { type Fact, factFor, type OnThisDay } from './onthisday';
import { teamTheme, THEME_VARS, themeVars } from './theme';
import { followGroups, followLabel, keywordKey, MAX_FOLLOWS, parseFollow, toggleFollow, topicKey } from './follow';
import { badgeColor, BREAKING_STEP_MS, briefing, byBreaking, coverage, discovery, FILM_ORDER, imageSrc, inOrder, initial, isStale, parseRoute, readerPage, safeUrl, sections, splitRecent, stories, storyLink, sportSections, mixSources, subtopicOf, teamStories, subtopicLabel, subtopicRoute, subtopicsOf, storyPage, timeAgo, TOPICS, topicLabel, topStory } from './feed';
import { dayKey, loadRead, markRead } from './briefing';
import { dividerAt, dividerLabel, loadLastVisit, MIN_GAP_MS, saveVisit, sinceWhen } from './visit';
import type { Route, Section, Story } from './feed';
import { dayRange, earningDate, earningDay, EARNINGS_DAYS, type Earning, type Earnings, earningTime, epsLabel, formatMove, historyChange, isFresh as marketsFresh, isMarketNews, marketPhase, earningsToday, stripMoves, type Markets, priceLabel, type Quote, sparkline, upcoming, watchTerms } from './markets';
import { usePullToRefresh } from './pull';
import { httpsOrigin, PUSH_NOTES, PUSH_SUMMARY, PUSH_TOPICS, pushState, registration, validTime, type PushEnv, type PushPrefs, type PushTopic, type Subscription } from './push';
import { disable as disablePush, enable as enablePush, readEnv } from './pushClient';
import { loadSettings, MAX_TEAM_CHARS, MAX_TEAMS, readSize, saveSettings, type Settings, shownCount, sourceNames, TEXT_SIZES, toggled, WATCH_KEY, withoutSources, withTeam } from './settings';
import type { Feed, Item, Topic } from './types';
import { teamSchedules, type Schedule, type TeamSchedule } from './schedule';
import { cricketUpcoming, type CricketMatch, type Game, hasScores, type LiveCard, liveNow, type Match, type ScoreView, scoresFor, type Scores, teamCards, teamMatcher, teamSuggestions } from './scores';
import { degrees, headline, hourBars, isFresh, tip, type Weather } from './weather';

/** What identifies a screen for scroll memory: its kind, plus the story, symbol or sub-topic it shows. */
const screenKeyOf = (r: Route): string =>
  r.kind === 'discovery' || r.kind === 'sports' || r.kind === 'films' ? `${r.kind}:${r.sub ?? ''}` : r.kind === 'home' || r.kind === 'local' || r.kind === 'markets' || r.kind === 'settings' ? r.kind : `${r.kind}:${r.id}`;
/** The Browse tab (was Discovery). Its route stays `#/discovery` and the code keeps the Discovery names so old links and bookmarks still work. */
const BROWSE = 'Browse';
const HOME_MARKETS_MS = 5 * 60 * 1000;  // quotes move every 5 minutes: the strip on For you looks again no sooner than that
const needsMarkets =(kind: string) => kind === 'home' || kind === 'markets' || kind === 'settings' || kind === 'quote';
const PAGE = 30;
const TICK_MS = 60_000;
const COVERAGE_SHOWN = 8;
const EXTERNAL = { target: '_blank', rel: 'noopener noreferrer' } as const;
type Load = { state: 'loading' } | { state: 'error' } | { state: 'ready'; feed: Feed };

/** The Technology list's header: the kernel's current releases, three rows. Folds to its header (with the Stable version). */
function KernelTable({ kernel, collapsed, onToggle }: { kernel: Kernel; collapsed: boolean; onToggle: () => void }) {
  return (
    <>
      <button type="button" class="grp fold-h" aria-expanded={!collapsed} onClick={onToggle}>
        <span>{kernelTitle(kernel, collapsed)}</span>
        <span class={'chev' + (collapsed ? '' : ' open')} aria-hidden="true">›</span>
      </button>
      {!collapsed && (
        <table class="ktable" aria-label="Linux kernel releases">
          <thead><tr><th scope="col">Branch</th><th scope="col">Version</th><th scope="col">Released</th></tr></thead>
          <tbody>
            {kernel.rows.map((r) => <tr key={r.branch}><th scope="row">{r.branch}</th><td>{r.version}</td><td>{r.released}</td></tr>)}
          </tbody>
        </table>
      )}
    </>
  );
}

function WeatherStrip({ weather, stale, now }: { weather: Weather; stale: boolean; now: Date }) {
  const [open, setOpen] = useState(false);  // the hourly strip; not remembered between visits
  if (stale) {  // never present an old forecast or its alerts as current
    return (
      <section class="wx" aria-label="Local weather">
        <div><div class="wx-k">LOCAL WEATHER</div><div class="wx-sub">Forecast is out of date. Check the National Weather Service for alerts.</div></div>
      </section>
    );
  }
  const alert = weather.alerts[0];
  const outlook = headline(weather, now);
  const range = weather.high !== null && weather.low !== null ? `H ${degrees(weather.high)} L ${degrees(weather.low)}` : '';
  const bars = hourBars(weather.hourly, now);
  const canOpen = bars.length > 0;
  const title = alert ? `${alert.event}${weather.alerts.length > 1 ? ` +${weather.alerts.length - 1}` : ''}` : outlook;
  const detail = (alert ? [outlook, `${degrees(weather.temp)} now`, range] : [range, tip(weather, now)]).filter(Boolean).join(' · ');
  const top = (
    <>
      <span class="wx-l">
        <span class="wx-k">{alert ? 'WEATHER ALERT · NATIONAL WEATHER SERVICE' : 'LOCAL WEATHER'}</span>
        <span class="wx-h">{title}</span>
        {detail && <span class="wx-d">{detail}</span>}
        {!weather.alertsOk && <span class="wx-sub">Weather alerts unavailable</span>}
      </span>
      <span class="wx-r">
        <b>{degrees(weather.temp)}</b>
        {canOpen && <span aria-hidden="true">{open ? 'Hide hours' : 'Tap for hours'}</span>}
      </span>
    </>
  );
  return (
    <section class={alert ? 'wx alert' : 'wx'} aria-label="Local weather">
      {canOpen
        ? <button type="button" class="wx-top" aria-expanded={open} onClick={() => setOpen((o) => !o)}>{top}</button>
        : <div class="wx-top">{top}</div>}
      {open && canOpen && (
        <div class="wx-hours">
          <ol>
            {bars.map((h, n) => (
              <li key={n} class={h.first ? 'first' : ''}>
                <span class="hl">{h.label}</span>
                <span class="bar" role="img" aria-label={`${Math.round(h.pop)}% chance of rain`}><i style={{ height: `${Math.max(3, Math.round(h.pop * 0.38))}px` }} /></span>
                <b>{degrees(h.temp)}</b>
              </li>
            ))}
          </ol>
          <p>Bars show the chance of rain each hour</p>
        </div>
      )}
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
        {s.sources > 1 && s.outlets && s.outlets.length > 1
          ? <Outlets outlets={s.outlets} total={s.sources} />
          : <Source name={s.item.source} when={s.sources > 1 ? '' : timeAgo(s.item.published, now)} extra={topicLabel(s.item.topic)} />}
        <h3>{s.item.title}</h3>
        {s.sources > 1 && (
          <div class="cl"><span class="pill">{s.sources} outlets</span><span>{[timeAgo(s.item.published, now), topicLabel(s.item.topic)].join(' · ')}</span></div>
        )}
      </div>
      <Pic item={s.item} class="thumb" onFail={() => setBroken(imageSrc(s.item))} />
    </StoryAnchor>
  );
}

function TopicSection({ section, now, onAll, since }: { section: Pick<Section, 'label' | 'color' | 'lead' | 'more' | 'total'>; now: Date; onAll?: () => void; since?: number }) {
  const { lead } = section;
  const split = since === undefined ? -1 : dividerAt([lead, ...section.more], since);  // 1 or more: the lead and some rows are new, the rest are not
  return (
    <section aria-label={section.label}>
      <div class="grp sech"><i style={{ background: section.color }} />{section.label}
        {onAll && <button type="button" class="all" onClick={onAll}>See all {section.total} ›</button>}</div>
      <StoryAnchor story={lead} class="lead">
        <Pic item={lead.item} class="pic" />
        <Source name={lead.item.source} when={timeAgo(lead.item.published, now)} />
        <h2>{lead.item.title}</h2>
      </StoryAnchor>
      {section.more.map((s, n) => (
        <Fragment key={s.item.id}>
          {n + 1 === split && since !== undefined && <NewDivider fresh={split} since={since} short />}
          <StoryRow s={s} now={now} />
        </Fragment>
      ))}
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

type Tab = 'home' | 'discovery' | 'local' | 'sports' | 'films' | 'markets';

/** `current` is null on screens that are not a tab (Settings). */
function TabBar({ hidden = false, current = 'home' }: { hidden?: boolean; current?: Tab | null }) {
  const link = (tab: Tab, href: string, label: string) =>
    current === tab ? <a class="on" href={href} aria-current="page">{label}</a> : <a href={href}>{label}</a>;
  return (
    <nav class={hidden ? 'tabbar hide' : 'tabbar'} aria-label="Sections">
      {link('home', '#', 'For you')}
      {link('local', '#/local', 'Local')}
      {link('sports', '#/sports', 'Sports')}
      {link('films', '#/films', 'Films')}
      {link('markets', '#/markets', 'Markets')}
      {link('discovery', '#/discovery', BROWSE)}
    </nav>
  );
}

/** The gear at the top right of each tab's header: Settings is not a tab. */
function SettingsLink() {
  return (
    <a class="ib" href="#/settings" aria-label="Settings" title="Settings">
      <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <circle cx="12" cy="12" r="3" />
        <path d="M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.9-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.9.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.9 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.9l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.9.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.9-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.9V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z" />
      </svg>
    </a>
  );
}

function QuoteRow({ q, index = false, earn, now }: { q: Quote; index?: boolean; earn?: Earning; now?: Date }) {
  const { text, dir } = formatMove(q.change, q.changePct, q.currency);
  const points = sparkline(q.series);
  return (
    <li>
      <a class="q" href={`#/quote/${encodeURIComponent(q.symbol)}`}>
        <div class="qn"><b>{q.name}</b><span>{q.symbol.replace('^', '')}</span>{earn && now && <EarnTag e={earn} now={now} />}</div>
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

/** "Earnings Thu · before open", red when it is today. */
function EarnTag({ e, now }: { e: Earning; now: Date }) {
  const day = earningDay(e.date, now);
  const time = earningTime(e.time);
  const when = day.today || day.label === 'Tomorrow' ? day.label.toLowerCase() : day.label;
  return <em class={day.today ? 'etag today' : 'etag'}>Earnings {when}{time ? ' · ' + time : ''}</em>;
}

function Stat({ label, value }: { label: string; value: string }) {
  return value ? <li><span>{label}</span><b>{value}</b></li> : null;
}

/** One watchlist symbol: today's numbers and the 3-month graph. */
function QuoteScreen({ markets, earnings, loaded, symbol, now, canGoBack }: { markets: Markets | undefined; earnings: Earnings | undefined; loaded: boolean; symbol: string; now: Date; canGoBack: boolean }) {
  const q = markets?.tickers.find((t) => t.symbol === symbol);
  const next = upcoming(earnings, [symbol], now)[0];
  const goBack = () => { if (canGoBack) history.back(); else location.hash = '#/markets'; };
  const move = q ? formatMove(q.change, q.changePct, q.currency) : undefined;
  // the stored history ends at an earlier (possibly in-progress) daily bar: end the graph on the live price
  const series = q && q.history.length > 1 ? [...q.history, q.price] : [];
  const trend = historyChange(series);
  const trendMove = trend && q ? formatMove(trend.change, trend.pct, q.currency) : undefined;
  const points = sparkline(series, 300, 120);
  const lo = series.length ? Math.min(...series) : undefined;
  const hi = series.length ? Math.max(...series) : undefined;
  const stale = markets ? !marketsFresh(markets.generated, now) : false;
  return (
    <div class="wrap">
      <div class="back"><button type="button" class="ib" aria-label="Back" onClick={goBack}>‹</button></div>
      <header class="hdr"><div><div class="e">{symbol}</div><h1>{q?.name ?? symbol}</h1></div></header>
      {markets && stale && <p class="note warn">Updated {timeAgo(markets.generated, now)}; prices may be out of date.</p>}
      {!q && <p class="note">{markets || loaded ? 'No quote for this symbol right now.' : 'Loading…'}</p>}
      {q && move && (
        <>
          <div class="qprice"><b>{priceLabel(q.price, q.currency, false)}</b><span class={`chg ${move.dir}`}>{move.text}</span></div>
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
          {next && (
            <>
              <div class="grp">Next earnings</div>
              <ul class="set stats">
                <Stat label="Date" value={earningDate(next.date)} />
                <Stat label="Time" value={next.time === 'pre' ? 'Before the open' : next.time === 'post' ? 'After the close' : 'Not announced'} />
                <Stat label="EPS estimate" value={next.eps !== null ? epsLabel(next.eps) : ''} />
              </ul>
            </>
          )}
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

/** The Browse screen (route and name kept as Discovery). Stories you would not otherwise open: the widest coverage, the newest, and the feed's sub-topics. A sub-topic opens its own list. */
function DiscoveryScreen({ feed, loaded, failed, now, sub, shown, onMore, onOpenSub, onOpenSports, onRetry, canGoBack, cornersCollapsed, onToggleCorners, following, onFollow }: {
  cornersCollapsed: boolean; onToggleCorners: () => void; following: string[]; onFollow: (key: string) => void;
  feed: Feed | undefined; loaded: boolean; failed: boolean; now: Date; sub: string | undefined; shown: number; onMore: () => void; onOpenSub: () => void; onOpenSports: () => void;
  onRetry: () => void; canGoBack: boolean;
}) {
  const all = useMemo(() => (feed ? stories(feed, 'all') : []), [feed]);
  const sportsAll = useMemo(() => (feed ? stories(feed, 'sports') : []), [feed]);
  const filmAll = useMemo(() => (feed ? stories(feed, 'entertainment') : []), [feed]);  // Browse has no film tiles now; this only sends an old bookmarked film link to the Films tab
  const scienceAll = useMemo(() => (feed ? stories(feed, 'science') : []), [feed]);  // Browse-only: not in For you
  const found = useMemo(() => discovery(all, now, scienceAll), [all, scienceAll, now]);
  const inSub = useMemo(() => {
    if (!sub) return [];
    return [...all, ...scienceAll].filter((s) => subtopicOf(s.item) === sub).sort((a, b) => b.item.published.localeCompare(a.item.published));  // newest first, as stories() does
  }, [all, scienceAll, sub]);
  const goBack = () => { if (canGoBack) history.back(); else location.hash = '#/discovery'; };
  useEffect(() => {  // an old link to a sports sub-topic (#/discovery/cricket) now lives in the Sports tab
    if (sub && feed && inSub.length === 0 && sportsAll.some((s) => s.item.subtopic === sub)) location.replace(subtopicRoute('sports', sub));
    else if (sub && feed && inSub.length === 0 && filmAll.some((s) => s.item.subtopic === sub)) location.replace(subtopicRoute('entertainment', sub));
  }, [sub, feed, inSub, sportsAll, filmAll]);
  const waiting = !feed && !failed && !loaded;
  return (
    <div class="wrap">
      {sub && <div class="back"><button type="button" class="ib" aria-label="Back" onClick={goBack}>‹</button></div>}
      <header class="hdr"><div><div class="e">{sub ? BROWSE : 'Beyond your top stories'}</div><h1>{sub ? subtopicLabel(sub) : BROWSE}</h1></div>{!sub && <SettingsLink />}{sub && <FollowButton sub={sub} following={following} onFollow={onFollow} />}</header>
      {waiting && <p class="note">Loading…</p>}
      {failed && !feed && (
        <div class="empty"><b>Can't load the news</b><span>Check your connection.</span>
          <button type="button" class="btn" onClick={onRetry}>Try again</button></div>
      )}
      {feed && isStale(feed.generated, now) && <p class="note warn">Updated {timeAgo(feed.generated, now)}; newer stories may be missing.</p>}
      {feed && sub && inSub.length === 0 && <div class="empty"><b>Nothing here yet</b><span>No stories in this sub-topic right now.</span></div>}
      {sub && inSub.slice(0, shown).map((s) => <StoryRow key={s.item.id} s={s} now={now} />)}
      {sub && inSub.length > shown && <div class="more"><button type="button" class="btn g" onClick={onMore}>Show more</button></div>}
      {feed && !sub && found.widely.length + found.justIn.length + found.corners.length === 0 && (
        <div class="empty"><b>Nothing to discover yet</b><span>Check back after the next update.</span></div>
      )}
      {!sub && found.corners.length > 0 && (
        <>
          <button type="button" class="grp fold-h" aria-expanded={!cornersCollapsed} onClick={onToggleCorners}>
            <span>Corners of the feed{cornersCollapsed ? ` (${found.corners.length})` : ''}</span>
            <span class={'chev' + (cornersCollapsed ? '' : ' open')} aria-hidden="true">›</span>
          </button>
          {!cornersCollapsed && (
            <div class="tiles">
              {found.corners.map((c) => (
                <a key={subtopicRoute(c.topic, c.id)} class="tile" href={subtopicRoute(c.topic, c.id)} onClick={c.topic === 'sports' ? onOpenSports : onOpenSub}>
                  <b>{c.label}</b>
                  <span class="tl">{c.lead.item.title}</span>
                  <span class="tn">{c.total} {c.total === 1 ? 'story' : 'stories'} · {timeAgo(c.lead.item.published, now)} ›</span>
                </a>
              ))}
            </div>
          )}
        </>
      )}
      {!sub && found.widely.length > 0 && (
        <>
          <div class="grp">Widely covered</div>
          {found.widely.map((s) => <StoryRow key={s.item.id} s={s} now={now} />)}
        </>
      )}
      {!sub && found.justIn.length > 0 && (
        <>
          <div class="grp">Just in</div>
          {found.justIn.map((s) => <StoryRow key={s.item.id} s={s} now={now} />)}
        </>
      )}
    </div>
  );
}

function Status({ state, detail }: { state: 'pre' | 'live' | 'final'; detail: string }) {
  return <div class={`st ${state}`}>{state === 'live' && <b>LIVE</b>}<span>{detail}</span></div>;
}

/** One NFL game: both sides and their scores; the leader of a finished game is in bold. */
function GameRow({ g }: { g: Game }) {
  const lead = g.state !== 'pre' && g.home.score !== null && g.away.score !== null && g.home.score !== g.away.score ? (g.home.score > g.away.score ? 'home' : 'away') : '';
  const body = (
    <>
      <div class="teams">
        <div class={g.state === 'final' && lead === 'away' ? 'win' : ''}><span>{g.away.name}</span><b>{g.away.score ?? ''}</b></div>
        <div class={g.state === 'final' && lead === 'home' ? 'win' : ''}><span>{g.home.name}</span><b>{g.home.score ?? ''}</b></div>
      </div>
      <Status state={g.state} detail={g.detail} />
    </>
  );
  return g.url ? <a class="g" href={g.url} {...EXTERNAL}>{body}</a> : <div class="g">{body}</div>;
}

function MatchRow({ m }: { m: Match }) {
  return (
    <div class="g">
      <div class="teams">
        {m.players.map((p) => <div key={p.name} class={p.winner ? 'win' : ''}><span>{p.name}</span><b>{p.sets.join(' ')}</b></div>)}
      </div>
      <Status state={m.state} detail={m.detail} />
    </div>
  );
}

function CricketRow({ c }: { c: CricketMatch }) {
  const body = <><div class="ln">{c.line}</div>{c.live ? <div class="st live"><b>LIVE</b></div> : cricketUpcoming(c) && <div class="st"><span>Upcoming</span></div>}</>;
  return c.url ? <a class="g" href={c.url} {...EXTERNAL}>{body}</a> : <div class="g">{body}</div>;
}

/** The "Live now" strip: a card per match in play, across every sport, scrolling sideways. */
function LiveStrip({ title, cards }: { title: string; cards: LiveCard[] }) {
  if (cards.length === 0) return null;
  return (
    <>
      <div class="grp">{title}<span class="cnt">{cards.length} {cards.length === 1 ? 'match' : 'matches'}</span></div>
      <div class="strip">
        {cards.map((c) => {
          const body = (
            <>
              <div class="top"><span>{c.sport}</span>{c.state === 'live' && <i>Live</i>}</div>
              {c.rows.map((r, i) => <div class="r" key={i}><span>{r.name}</span><b>{r.score}</b></div>)}
              {c.line && <div class="cl">{c.line}</div>}
              {c.note && <div class="sub">{c.note}</div>}
            </>
          );
          return c.url ? <a key={c.key} class="lc" href={c.url} {...EXTERNAL}>{body}</a> : <div key={c.key} class="lc">{body}</div>;
        })}
      </div>
    </>
  );
}

/** A score section's heading. It folds the section (the choice is kept on the phone); under All it also links to the sport's own
 * list when more rows exist than are shown. */
function Group({ title, sport, shown, total, all, foldable = true, folded, onFold }: {
  title: string; sport?: string; shown: number; total: number; all: boolean; foldable?: boolean; folded?: boolean; onFold?: (sport: string) => void;
}) {
  if (!foldable || !sport || !onFold) return <div class="grp">{title}</div>;
  return (
    <div class="grp ghead">
      <button type="button" class="gfold" aria-expanded={!folded} onClick={() => onFold(sport)}>
        <span>{title}{folded ? ` · ${total}` : ''}</span><span class={`chev${folded ? '' : ' open'}`} aria-hidden="true">›</span>
      </button>
      {all && !folded && total > shown && <a class="cnt" href={`#/sports/${sport}`}>All {total}</a>}
    </div>
  );
}

/** The scores part of the Sports tab: rows per sport, or a note when they are out of date or could not be read. */
function ScoresPanel({ view, generated, now, all, collapsed, onFold }: {
  view: ScoreView; generated: string; now: Date; all: boolean; collapsed: string[]; onFold: (sport: string) => void;
}) {
  if (view.stale) return <p class="note warn">Scores are out of date (updated {timeAgo(generated, now)}).</p>;
  const tennisShown = view.tennis.reduce((n, g) => n + g.matches.length, 0);
  const folded = (sport: string) => collapsed.includes(sport);
  const tennis = folded('tennis') ? view.tennis.slice(0, 1) : view.tennis;  // folded: one heading for the whole sport
  return (
    <>
      {view.down.length > 0 && <p class="note">{view.down.join(' and ')} scores are unavailable right now.</p>}
      {view.nfl.length > 0 && (
        <>
          <Group title="NFL" sport="nfl" shown={view.nfl.length} total={view.total.nfl} all={all} folded={folded('nfl')} onFold={onFold} />
          {!folded('nfl') && <div class="sc">{view.nfl.map((g) => <GameRow key={g.id} g={g} />)}</div>}
        </>
      )}
      {view.cricket.length > 0 && (
        <>
          <Group title="Cricket" sport="cricket" shown={view.cricket.length} total={view.total.cricket} all={all} folded={folded('cricket')} onFold={onFold} />
          {!folded('cricket') && <div class="sc">{view.cricket.map((c) => <CricketRow key={c.id} c={c} />)}</div>}
        </>
      )}
      {tennis.map((t, i) => (  // only the first tournament's heading folds the sport (and, under All, links to its list)
        <div key={t.tournament}>
          <Group title={folded('tennis') ? 'Tennis' : t.tournament || 'Tennis'} sport="tennis" shown={tennisShown} total={view.total.tennis}
            all={all && i === 0} foldable={i === 0} folded={folded('tennis')} onFold={onFold} />
          {!folded('tennis') && <div class="sc">{t.matches.map((m) => <MatchRow key={m.id} m={m} />)}</div>}
        </div>
      ))}
    </>
  );
}

/** The next games of each followed NFL team, with local kickoff times and the weeks off. */
function ScheduleCard({ items, collapsed, onToggle }: { items: TeamSchedule[]; collapsed: boolean; onToggle: () => void }) {
  const [all, setAll] = useState(false);
  const total = items.length;
  return (
    <>
      <button type="button" class="grp fold-h" aria-expanded={!collapsed} onClick={onToggle}>
        <span>My schedule{collapsed ? ' (' + total + (total === 1 ? ' team)' : ' teams)') : ''}</span>
        <span class={'chev' + (collapsed ? '' : ' open')} aria-hidden="true">›</span>
      </button>
      {!collapsed && (
        <div class="sc sched">
          {items.map((t) => {
            const rows = all ? t.rows : t.rows.slice(0, SCHEDULE_ROWS);
            return (
              <div key={t.team}>
                <div class="st-team"><b>{t.team}</b></div>
                {rows.map((r) => r.kind === 'bye' ? (
                  <div key={'bye' + r.week} class="gm bye"><div class="d"><b>Bye</b><span>no game</span></div><div class="o">Week off</div><div class="w">Wk {r.week}</div></div>
                ) : (
                  <div key={r.game.id} class="gm">
                    <div class="d"><b>{new Date(r.game.start).toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric' })}</b>
                      <span>{new Date(r.game.start).toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })}</span></div>
                    <div class="o"><span>{r.atHome ? 'vs' : 'at'}</span> {r.opponent}</div>
                    <div class="w">Wk {r.week}</div>
                  </div>
                ))}
              </div>
            );
          })}
          {items.some((t) => t.rows.length > SCHEDULE_ROWS) && (
            <button type="button" class="more-sched" onClick={() => setAll(!all)}>{all ? 'Show fewer' : 'Show the rest of the season'}</button>
          )}
        </div>
      )}
    </>
  );
}

/** Every sports story, newest first (a story many sources cover ranks a little higher, and no source runs on for long), with a chip per sub-topic (NFL, cricket, tennis). */
function SportsScreen({ feed, scores, schedule, scheduleCollapsed, onToggleSchedule, collapsed, onFold, teams, loaded, failed, now, sub, shown, onMore, onPick, onRetry, following, onFollow }: {
  following: string[]; onFollow: (key: string) => void;
  feed: Feed | undefined; scores: Scores | undefined; schedule: Schedule | undefined; scheduleCollapsed: boolean; onToggleSchedule: () => void; collapsed: string[]; onFold: (sport: string) => void; teams: string[]; loaded: boolean; failed: boolean; now: Date; sub: string | undefined; shown: number; onMore: () => void; onPick: () => void; onRetry: () => void;
}) {
  const step = Math.floor(now.getTime() / BREAKING_STEP_MS);  // re-rank only every few minutes
  const rankNow = useMemo(() => new Date(step * BREAKING_STEP_MS), [step]);
  const all = useMemo(() => (feed ? mixSources(byBreaking(stories(feed, 'sports'), rankNow)) : []), [feed, rankNow]);
  const subs = useMemo(() => subtopicsOf(all), [all]);
  const list = useMemo(() => (sub ? mixSources(all.filter((s) => s.item.subtopic === sub)) : all), [all, sub]);  // mixed again once filtered
  const scoreView = useMemo(() => scoresFor(scores, sub, now), [scores, sub, now]);
  const live = useMemo(() => liveNow(scores, now), [scores, now]);
  const mine = useMemo(() => teamCards(scores, teams, now), [scores, teams, now]);
  const mySchedule = useMemo(() => teamSchedules(schedule, teams, now), [schedule, teams, now]);
  const liveRest = useMemo(() => live.filter((c) => !mine.some((m) => m.key === c.key)), [live, mine]);  // a followed live game is in My teams only
  const mineStories = useMemo(() => teamStories(all, teamMatcher(teams)).slice(0, 3), [all, teams]);
  const pick = (next: string | undefined) => { onPick(); location.hash = next ? `#/sports/${next}` : '#/sports'; };
  const sportGroups = useMemo(() => sportSections(all), [all]);
  const page = list.slice(0, shown);
  const lead = page.find((s) => imageSrc(s.item) !== undefined);  // the first story with a picture opens the list as a big card
  const rest = lead ? page.filter((s) => s !== lead) : page;
  return (
    <div class="wrap">
      <header class="hdr"><div><div class="e">Scores and stories</div><h1>Sports</h1></div><div class="hact">{sub && <FollowButton sub={sub} following={following} onFollow={onFollow} />}<SettingsLink /></div></header>
      <nav class="chips" aria-label="Sports">
        <button type="button" class={!sub ? 'on' : ''} aria-pressed={!sub} onClick={() => pick(undefined)}>All</button>
        {subs.map((id) => (
          <button key={id} type="button" class={id === sub ? 'on' : ''} aria-pressed={id === sub} onClick={() => pick(id)}>{subtopicLabel(id)}</button>
        ))}
        {sub && !subs.includes(sub) && <button type="button" class="on" aria-pressed="true">{subtopicLabel(sub)}</button>}
      </nav>
      {!sub && teams.length === 0 && <p class="note"><a href="#/settings">Follow your teams</a> to see their games and stories here.</p>}
      {!sub && <LiveStrip title="My teams" cards={mine} />}
      {!sub && mySchedule.length > 0 && <ScheduleCard items={mySchedule} collapsed={scheduleCollapsed} onToggle={onToggleSchedule} />}
      {!sub && <LiveStrip title="Live now" cards={liveRest} />}
      {scoreView && scores && <ScoresPanel view={scoreView} generated={scores.generated} now={now} all={!sub} collapsed={collapsed} onFold={onFold} />}
      {!feed && !failed && !loaded && <p class="note">Loading sports…</p>}
      {failed && !feed && (
        <div class="empty"><b>Can't load the news</b><span>Check your connection.</span>
          <button type="button" class="btn" onClick={onRetry}>Try again</button></div>
      )}
      {feed && isStale(feed.generated, now) && <p class="note warn">Updated {timeAgo(feed.generated, now)}; newer stories may be missing.</p>}
      {feed && list.length === 0 && <div class="empty"><b>No sports stories yet</b><span>{sub ? 'Nothing in this sport right now.' : 'Sports stories appear here.'}</span></div>}
      {!sub && mineStories[0] && <TopicSection section={{ label: 'My teams', color: '#c97aa8', lead: mineStories[0], more: mineStories.slice(1), total: mineStories.length }} now={now} />}
      {!sub && sportGroups.map((g) => <TopicSection key={g.sub} section={g} now={now} onAll={() => pick(g.sub)} />)}
      {sub && list.length > 0 && hasScores(scoreView) && <div class="grp">Top stories</div>}
      {sub && lead && (
        <StoryAnchor story={lead} class="lead">
          <Pic item={lead.item} class="pic" />
          <Source name={lead.item.source} when={timeAgo(lead.item.published, now)} />
          <h2>{lead.item.title}</h2>
        </StoryAnchor>
      )}
      {sub && rest.map((s) => <StoryRow key={s.item.id} s={s} now={now} />)}
      {sub && list.length > shown && <div class="more"><button type="button" class="btn g" onClick={onMore}>Show more</button></div>}
    </div>
  );
}

/** The Films tab: Bollywood, South Cinema and Hollywood stories, a section per sub-topic (a picture lead, then two more) with a chip each; a chip or "All" opens one list. */
function FilmsScreen({ feed, loaded, failed, now, sub, shown, onMore, onPick, onRetry, following, onFollow }: {
  following: string[]; onFollow: (key: string) => void;
  feed: Feed | undefined; loaded: boolean; failed: boolean; now: Date; sub: string | undefined; shown: number; onMore: () => void; onPick: () => void; onRetry: () => void;
}) {
  const step = Math.floor(now.getTime() / BREAKING_STEP_MS);
  const rankNow = useMemo(() => new Date(step * BREAKING_STEP_MS), [step]);
  const all = useMemo(() => (feed ? mixSources(byBreaking(stories(feed, 'entertainment'), rankNow)) : []), [feed, rankNow]);
  const subs = useMemo(() => inOrder(subtopicsOf(all), FILM_ORDER), [all]);
  const list = useMemo(() => (sub ? mixSources(all.filter((s) => s.item.subtopic === sub)) : all), [all, sub]);
  const groups = useMemo(() => subs.flatMap((id) => sportSections(all.filter((s) => s.item.subtopic === id))), [all, subs]);  // one section per sub-topic, in the tab's order
  const pick = (next: string | undefined) => { onPick(); location.hash = next ? `#/films/${next}` : '#/films'; };
  const page = list.slice(0, shown);
  const lead = page.find((s) => imageSrc(s.item) !== undefined);
  const rest = lead ? page.filter((s) => s !== lead) : page;
  return (
    <div class="wrap">
      <header class="hdr"><div><div class="e">Movies and celebrities</div><h1>Entertainment</h1></div><div class="hact">{sub && <FollowButton sub={sub} following={following} onFollow={onFollow} />}<SettingsLink /></div></header>
      <nav class="chips" aria-label="Entertainment">
        <button type="button" class={!sub ? 'on' : ''} aria-pressed={!sub} onClick={() => pick(undefined)}>All</button>
        {subs.map((id) => (
          <button key={id} type="button" class={id === sub ? 'on' : ''} aria-pressed={id === sub} onClick={() => pick(id)}>{subtopicLabel(id)}</button>
        ))}
        {sub && !subs.includes(sub) && <button type="button" class="on" aria-pressed="true">{subtopicLabel(sub)}</button>}
      </nav>
      {!feed && !failed && !loaded && <p class="note">Loading…</p>}
      {failed && !feed && (
        <div class="empty"><b>Can't load the news</b><span>Check your connection.</span>
          <button type="button" class="btn" onClick={onRetry}>Try again</button></div>
      )}
      {feed && isStale(feed.generated, now) && <p class="note warn">Updated {timeAgo(feed.generated, now)}; newer stories may be missing.</p>}
      {feed && list.length === 0 && <div class="empty"><b>No stories yet</b><span>{sub ? 'Nothing here right now.' : 'Film stories appear here.'}</span></div>}
      {!sub && groups.map((g) => <TopicSection key={g.sub} section={g} now={now} onAll={() => pick(g.sub)} />)}
      {sub && lead && (
        <StoryAnchor story={lead} class="lead">
          <Pic item={lead.item} class="pic" />
          <Source name={lead.item.source} when={timeAgo(lead.item.published, now)} />
          <h2>{lead.item.title}</h2>
        </StoryAnchor>
      )}
      {sub && rest.map((s) => <StoryRow key={s.item.id} s={s} now={now} />)}
      {sub && list.length > shown && <div class="more"><button type="button" class="btn g" onClick={onMore}>Show more</button></div>}
    </div>
  );
}

/** Everything local: the forecast and alerts, then every local story, the last 24 hours first. */
function LocalScreen({ feed, loaded, failed, weather, weatherStale, now, shown, onMore, onRetry }: {
  feed: Feed | undefined; loaded: boolean; failed: boolean; weather: Weather | undefined; weatherStale: boolean; now: Date; shown: number; onMore: () => void; onRetry: () => void;
}) {
  const local = useMemo(() => (feed ? stories(feed, 'local') : []), [feed]);  // the sort depends on the feed only; the split on the clock
  const { recent, earlier } = useMemo(() => splitRecent(local, now), [local, now]);
  const recentShown = recent.slice(0, shown);
  const earlierShown = earlier.slice(0, Math.max(0, shown - recent.length));
  const empty = feed !== undefined && recent.length + earlier.length === 0;
  return (
    <div class="wrap">
      <header class="hdr"><div><div class="e">Near you</div><h1>Local</h1></div><SettingsLink /></header>
      {weather && <WeatherStrip weather={weather} stale={weatherStale} now={now} />}
      {!feed && !failed && !loaded && <p class="note">Loading local stories…</p>}
      {failed && !feed && (
        <div class="empty"><b>Can't load the news</b><span>Check your connection.</span>
          <button type="button" class="btn" onClick={onRetry}>Try again</button></div>
      )}
      {feed && isStale(feed.generated, now) && <p class="note warn">Updated {timeAgo(feed.generated, now)}; newer stories may be missing.</p>}
      {empty && <div class="empty"><b>No local stories yet</b><span>Local stories from your town's feeds appear here.</span></div>}
      {recentShown.length > 0 && (
        <>
          <div class="grp">Last 24 hours</div>
          {recentShown.map((s) => <StoryRow key={s.item.id} s={s} now={now} />)}
        </>
      )}
      {earlierShown.length > 0 && (
        <>
          <div class="grp">Earlier</div>
          {earlierShown.map((s) => <StoryRow key={s.item.id} s={s} now={now} />)}
        </>
      )}
      {recent.length + earlier.length > shown && <div class="more"><button type="button" class="btn g" onClick={onMore}>Show more</button></div>}
    </div>
  );
}

const SCHEDULE_RECHECK_MS = 30 * 60_000;
const SCHEDULE_ROWS = 4;  // games (or weeks off) listed per team before "Show the rest of the season"
const MARKET_NEWS_PAGE = 20;  // market stories shown, and added by each "Show more"

function MarketsScreen({ markets, earnings, hasKey, loaded, now, hidden, collapsed, onToggle, earnCollapsed, onToggleEarn, feed, onAllBusiness }: {
  markets: Markets | undefined; earnings: Earnings | undefined; hasKey: boolean; loaded: boolean; now: Date; hidden: string[]; collapsed: boolean; onToggle: () => void;
  earnCollapsed: boolean; onToggleEarn: () => void; feed: Feed | undefined; onAllBusiness: () => void;
}) {
  const tickers = markets ? markets.tickers.filter((q) => !hidden.includes(q.symbol)) : [];
  const soon = useMemo(() => upcoming(earnings, tickers.map((q) => q.symbol), now, EARNINGS_DAYS), [earnings, tickers, now]);
  const nextBy = useMemo(() => new Map(soon.map((e) => [e.symbol, e] as const)), [soon]);
  const stale = markets ? !marketsFresh(markets.generated, now) : false;
  const open = markets && !stale ? tickers.some((q) => q.open) : false;  // `open` is frozen at build time
  const traded = tickers.find((q) => q.lastTrade)?.lastTrade;
  const news = useMemo(() => {
    if (!feed) return [];
    const top = topStory(stories(feed, 'all'), now);  // the For You top story is not repeated here
    const terms = watchTerms(markets?.tickers ?? []);
    return stories(feed, 'business').filter((s) => s.item.id !== top?.item.id && isMarketNews(s.item, terms));
  }, [feed, now, markets]);
  const [newsShown, setNewsShown] = useState(MARKET_NEWS_PAGE);
  return (
    <div class="wrap">
      <header class="hdr">
        <div>
          <div class="e">{tickers.length > 0 ? (open ? 'Market open' : 'Market closed') : 'Markets'}</div>
          <h1>Markets</h1>
        </div>
        <SettingsLink />
      </header>
      {!hasKey && <p class="note">Your watchlist is private. Add your key and symbols in Settings.</p>}
      {hasKey && !markets && !loaded && <p class="note">Loading quotes…</p>}
      {hasKey && !markets && loaded && <p class="note">No watchlist quotes yet. Add symbols in Settings; they appear within a few minutes.</p>}
      {markets && stale && <p class="note warn">Updated {timeAgo(markets.generated, now)}; prices may be out of date.</p>}
      {soon.length > 0 && (
        <>
          <button type="button" class="grp fold-h" aria-expanded={!earnCollapsed} onClick={onToggleEarn}>
            <span>Upcoming earnings{earnCollapsed ? ' (' + soon.length + ')' : ''}</span><span class={'chev' + (earnCollapsed ? '' : ' open')} aria-hidden="true">›</span>
          </button>
          {!earnCollapsed && (
            <ul class="ql">
              {soon.map((e) => {
                const q = tickers.find((t) => t.symbol === e.symbol);
                const day = earningDay(e.date, now);
                return (
                  <li key={e.symbol}>
                    <a class={day.today ? 'er today' : 'er'} href={'#/quote/' + encodeURIComponent(e.symbol)}>
                      <div class="when"><b>{day.label}</b><span>{earningTime(e.time)}</span></div>
                      <div class="qn"><b>{e.symbol.replace('^', '')}</b><span>{q?.name ?? ''}</span></div>
                      <div class="eps">{e.eps !== null && <><b>{epsLabel(e.eps)}</b><span>EPS est.</span></>}</div>
                    </a>
                  </li>
                );
              })}
            </ul>
          )}
        </>
      )}
      {tickers.length > 0 && (
        <>
          <button type="button" class="grp fold-h" aria-expanded={!collapsed} onClick={onToggle}>
            <span>Watchlist{collapsed ? ` (${tickers.length})` : ''}</span><span class={`chev${collapsed ? '' : ' open'}`} aria-hidden="true">›</span>
          </button>
          {!collapsed && <ul class="ql">{tickers.map((q) => <QuoteRow key={q.symbol} q={q} earn={nextBy.get(q.symbol)} now={now} />)}</ul>}
        </>
      )}
      {!collapsed && markets && markets.missing > 0 && <p class="note">{markets.missing} {markets.missing === 1 ? 'quote is' : 'quotes are'} unavailable right now.</p>}
      {tickers.length > 0 && !collapsed && (
        <p class="fine">
          {traded ? `Last trade ${timeAgo(traded, now)}. ` : ''}Delayed, unofficial data from Yahoo Finance. Not investment advice.
        </p>
      )}
      {news.length > 0 && (
        <>
          <div class="grp">Market news</div>
          {news.slice(0, newsShown).map((s) => <StoryRow key={s.item.id} s={s} now={now} />)}
          <div class="btns">
            {news.length > newsShown && <button type="button" class="btn g" onClick={() => setNewsShown((n) => n + MARKET_NEWS_PAGE)}>Show more</button>}
            <button type="button" class="btn g" onClick={onAllBusiness}>All Business ›</button>
          </div>
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

/** The Follow button on a sub-topic's list: it shows whether the topic is followed and flips that. */
function FollowButton({ sub, following, onFollow }: { sub: string; following: string[]; onFollow: (key: string) => void }) {
  const key = topicKey(sub);
  const on = following.includes(key);
  const full = !on && following.length >= MAX_FOLLOWS;
  return (
    <button type="button" class={'fbtn' + (on ? ' on' : '')} aria-pressed={on} disabled={full} onClick={() => onFollow(key)}>
      {on ? '✓ Following' : '+ Follow'}
    </button>
  );
}

/** For you's Following section: each followed topic or keyword with its newest few stories. */
function FollowingSection({ groups, now }: { groups: ReturnType<typeof followGroups>; now: Date }) {
  if (groups.length === 0) return null;
  return (
    <section aria-label="Following">
      <div class="grp row-between">Following<a class="manage" href="#/settings">Manage ›</a></div>
      {groups.map((g) => (
        <div key={g.key} class="fgroup">
          <div class="grp sech"><i style={{ background: 'var(--accent)' }} />{g.label}
            {g.route ? <a class="all" href={g.route}>See all {g.total} ›</a> : <span class="all">{g.total} {g.total === 1 ? 'story' : 'stories'}</span>}</div>
          {g.stories.map((s) => <StoryRow key={s.item.id} s={s} now={now} />)}
        </div>
      ))}
    </section>
  );
}

/** Settings: the follows, each removable, and a box to follow a keyword (words separated by commas: any of them counts). */
function FollowEditor({ following, onChange }: { following: string[]; onChange: (next: string[]) => void }) {
  const [text, setText] = useState('');
  const key = keywordKey(text);
  const full = following.length >= MAX_FOLLOWS;
  const add = () => { if (key) { onChange(toggleFollow(following.filter((k) => k !== key), key)); setText(''); } };
  return (
    <div class="teams">
      {following.length > 0 && (
        <ul class="tchips">
          {following.map((k) => {
            const f = parseFollow(k);
            const label = f ? (f.kind === 'topic' ? followLabel(f) : f.words.join(', ')) : k;
            return <li key={k}><button type="button" aria-label={`Stop following ${label}`} onClick={() => onChange(following.filter((x) => x !== k))}>{label} <span aria-hidden="true">×</span></button></li>;
          })}
        </ul>
      )}
      {following.length === 0 && <p class="note">Nothing followed yet. Follow a topic from its list, or add a keyword here.</p>}
      <form class="fld trow" onSubmit={(e) => { e.preventDefault(); add(); }}>
        <input type="text" value={text} maxLength={120} placeholder="US election, midterms" aria-label="Keyword to follow"
          onInput={(e) => setText((e.currentTarget as HTMLInputElement).value)} />
        <button type="submit" class="btn" disabled={!key || (full && !following.includes(key))}>Follow</button>
      </form>
      {full && <p class="note" role="status">You follow {MAX_FOLLOWS} things, the most there is room for. Remove one to add another.</p>}
      <p class="fine">Separate words with commas; a story with any of them counts. Matches the start of a word in the headline or summary.</p>
    </div>
  );
}

/** Follow teams, countries or players by name: they are matched against the scores and the story headlines. */
function TeamsEditor({ teams, suggestions, onChange }: { teams: string[]; suggestions: string[]; onChange: (next: string[]) => void }) {
  const [text, setText] = useState('');
  const add = (name: string) => { onChange(withTeam(teams, name)); setText(''); };
  const offered = suggestions.filter((n) => !teams.some((t) => t.toLowerCase() === n.toLowerCase())).slice(0, 12);
  return (
    <div class="teams">
      {teams.length > 0 && (
        <ul class="tchips">
          {teams.map((t) => <li key={t}><button type="button" aria-label={`Stop following ${t}`} onClick={() => onChange(teams.filter((x) => x !== t))}>{t} <span aria-hidden="true">×</span></button></li>)}
        </ul>
      )}
      <form class="fld trow" onSubmit={(e) => { e.preventDefault(); add(text); }}>
        <input type="text" value={text} maxLength={MAX_TEAM_CHARS} placeholder="Bears, India, Sinner…" aria-label="Team, country or player" autocapitalize="words"
          onInput={(e) => setText((e.currentTarget as HTMLInputElement).value)} />
        <button type="submit" class="btn" disabled={!text.trim() || teams.length >= MAX_TEAMS}>Follow</button>
      </form>
      {offered.length > 0 && (
        <div class="tsug"><span>In the scores now:</span>{offered.map((n) => <button key={n} type="button" onClick={() => add(n)}>+ {n}</button>)}</div>
      )}
    </div>
  );
}

/** Notifications: turn them on for this device, choose what to be told about, and copy the registration that goes into SSM
 *  (docs/PUSH.md). There is no server to send it to: the subscription never leaves the phone except by this copy. */
function PushSection({ prefs, onChange }: { prefs: PushPrefs; onChange: (next: PushPrefs) => void }) {
  const [info, setInfo] = useState<{ env: PushEnv; sub: Subscription | undefined } | undefined>();
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState('');
  const [manual, setManual] = useState('');  // the registration shown for hand copying when the clipboard is not available
  useEffect(() => {
    const reread = () => { if (document.visibilityState === 'visible') void readEnv().then(setInfo); };  // back from iOS Settings: pick up a changed permission
    reread();
    document.addEventListener('visibilitychange', reread);
    return () => document.removeEventListener('visibilitychange', reread);
  }, []);
  if (!info) return null;
  const state = pushState(info.env);
  const sub = info.sub;
  const topicChange = (id: PushTopic, on: boolean) => onChange({ ...prefs, topics: PUSH_TOPICS.map((t) => t.id).filter((x) => (x === id ? on : prefs.topics.includes(x))) });
  const timeChange = (key: 'quietStart' | 'quietEnd', value: string) => { if (validTime(value)) onChange({ ...prefs, [key]: value }); };
  const run = async (job: () => Promise<string | undefined>, failed: string) => {
    setBusy(true);
    setMsg('');
    try {
      const note = await job();
      if (note) setMsg(note);
    } catch {
      setMsg(failed);
    } finally {
      setInfo(await readEnv());  // never throws
      setBusy(false);
    }
  };
  const turnOn = async () => (await enablePush()) ? undefined : 'Notifications were not turned on. If you dismissed the iOS prompt, allow them in iOS Settings and try again.';
  const turnOff = async () => { await disablePush(); return undefined; };
  const copy = () => {
    if (!sub) return;
    const site = httpsOrigin(location.origin);
    if (!site) { setMsg('Open the installed app (its https address, not a local one) to copy the registration.'); return; }
    const text = registration(sub, prefs, Intl.DateTimeFormat().resolvedOptions().timeZone, site);
    const manually = () => { setMsg('Could not copy automatically: select the text below and copy it.'); setManual(text); };
    setManual('');
    if (!navigator.clipboard) { manually(); return; }  // not a secure page, or a restricted browser view
    navigator.clipboard.writeText(text).then(() => setMsg('Copied. Paste it into the SSM parameter /news/push/registration (see docs/PUSH.md).'), manually);
  };
  return (
    <details class="card fold">
      <summary>Notifications{PUSH_SUMMARY[state] ? ` (${PUSH_SUMMARY[state]})` : ''}</summary>
      <p class="note" role="status">{PUSH_NOTES[state]}</p>
      {(state === 'off' || state === 'no-key') && (
        <div class="btns">
          <button type="button" class="btn" disabled={state === 'no-key' || busy} onClick={() => void run(turnOn, 'Could not turn notifications on. Reload the app and try again.')}>Turn on notifications</button>
        </div>
      )}
      {(state === 'off' || state === 'no-key' || state === 'enabled') && (
        <>
          <ul class="set inner">
            {PUSH_TOPICS.map((t) => (
              <li key={t.id}><label>{t.label} stories
                <input type="checkbox" checked={prefs.topics.includes(t.id)} onChange={(e) => topicChange(t.id, e.currentTarget.checked)} />
              </label></li>
            ))}
            <li><label>Weather alerts
              <input type="checkbox" checked={prefs.weather} onChange={(e) => onChange({ ...prefs, weather: e.currentTarget.checked })} />
            </label></li>
            <li><label>Village alerts
              <input type="checkbox" checked={prefs.alerts} onChange={(e) => onChange({ ...prefs, alerts: e.currentTarget.checked })} />
            </label></li>
            <li><label>Quiet from
              <input type="time" value={prefs.quietStart} onChange={(e) => timeChange('quietStart', e.currentTarget.value)} />
            </label></li>
            <li><label>Quiet until
              <input type="time" value={prefs.quietEnd} onChange={(e) => timeChange('quietEnd', e.currentTarget.value)} />
            </label></li>
          </ul>
          <p class="note">Village alerts come from your village's own alert feed and are sent even during quiet hours.</p>
          {prefs.topics.length === 0 && <p class="note">No news topics are chosen, so only {[prefs.weather && 'weather alerts', prefs.alerts && 'village alerts'].filter(Boolean).join(' and ') || 'nothing'} will be sent.</p>}
        </>
      )}
      {state === 'enabled' && (
        <div class="btns">
          <button type="button" class="btn" disabled={busy} onClick={copy}>Copy registration</button>
          <button type="button" class="btn g" disabled={busy} onClick={() => void run(turnOff, 'Could not turn notifications off.')}>Turn off</button>
        </div>
      )}
      {state === 'enabled' && <p class="fine">After changing what you want to hear about, copy the registration again and paste it into SSM.</p>}
      {msg && <p class="note" role="status">{msg}</p>}
      {manual && <label class="fld" style={{ margin: '8px 0' }}>Registration<textarea readOnly rows={5} value={manual} onFocus={(e) => e.currentTarget.select()} /></label>}
    </details>
  );
}

function SettingsScreen({ settings, update, sources, suggestions, markets, marketsLoaded, onSaved, canGoBack }: {
  settings: Settings; update: (next: Partial<Settings>) => void; sources: string[]; suggestions: string[]; markets: Markets | undefined; marketsLoaded: boolean;
  onSaved: (key: string) => void; canGoBack: boolean;
}) {
  const symbols = [...new Map([...(markets?.tickers ?? []).map((q) => [q.symbol, `${q.name} · ${q.symbol}`] as const),
    ...settings.hiddenTickers.map((t) => [t, t] as const)]).entries()];  // a hidden symbol no longer in the list can still be switched back on
  return (
    <div class="wrap">
      <div class="back"><button type="button" class="ib" aria-label="Back" onClick={() => { if (canGoBack) history.back(); else location.hash = '#'; }}>‹</button></div>
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
      <details class="card fold">
        <summary>Following{settings.following.length > 0 ? ` (${settings.following.length})` : ''}</summary>
        <FollowEditor following={settings.following} onChange={(following) => update({ following })} />
      </details>
      <details class="card fold">
        <summary>My teams{settings.myTeams.length > 0 ? ` (${settings.myTeams.length} followed)` : ''}</summary>
        <TeamsEditor teams={settings.myTeams} suggestions={suggestions} onChange={(myTeams) => update({ myTeams })} />
        <ul class="set inner">
          <li><label>Team colours on Sports
            <input type="checkbox" checked={settings.teamColors} onChange={() => update({ teamColors: !settings.teamColors })} />
          </label></li>
        </ul>
      </details>
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
      <PushSection prefs={settings.push} onChange={(push) => update({ push })} />
      <p class="fine">Saved on this device only. Hiding a source or symbol does not delete it. The symbol list itself is kept privately on the server.</p>
    </div>
  );
}

/** Home: the watchlist's biggest moves on one line and today's earnings. Hidden without a watchlist, quotes or fresh prices. */
function MarketsStrip({ markets, earnings, hidden, now }: { markets: Markets | undefined; earnings: Earnings | undefined; hidden: string[]; now: Date }) {
  if (!markets || !marketsFresh(markets.generated, now)) return null;
  const shown = markets.tickers.filter((q) => !hidden.includes(q.symbol));
  const { moves, more } = stripMoves(shown);
  const reports = earningsToday(earnings, shown.map((q) => q.symbol), now);
  if (moves.length === 0 && reports.length === 0) return null;
  const phase = marketPhase(markets, now);
  return (
    <a class="mk" href="#/markets" aria-label="Markets watchlist">
      <div class="mkh"><b>Markets · {phase}</b></div>
      {moves.length > 0 && (
        <div class="mkm">
          {moves.map((m) => <div key={m.symbol}><b>{m.symbol}</b><span class={`chg ${m.dir}`}>{m.text}</span></div>)}
          {more > 0 && <div class="mkmore"><span class="chg">+{more} more</span></div>}
        </div>
      )}
      {reports.length > 0 && <div class="mke">Earnings today: <b>{reports.join(', ')}</b></div>}
    </a>
  );
}

/** Today's briefing: the day's best-covered stories and how many are read; the heading says "You're caught up" once all are. */
function Briefing({ stories: list, read, onOpen, now, fact }: { stories: Story[]; read: string[]; onOpen: (id: string) => void; now: Date; fact?: Fact }) {
  if (list.length === 0) return null;
  const done = list.filter((s) => read.includes(s.item.id)).length;
  const caught = done === list.length;
  return (
    <section class="brief" aria-label="Your briefing">
      <div class="bh"><b>{caught ? "You're caught up" : 'Your briefing'}</b><span>{list.length} stories</span></div>
      {list.map((s, n) => (
        <a key={s.item.id} class={read.includes(s.item.id) ? 'bi seen' : 'bi'} href={storyLink(s)} onClick={() => onOpen(s.item.id)}>
          <span class="bn">{n + 1}</span>
          <div class="bt">
            <b>{s.item.title}</b>
            <small>{[topicLabel(s.item.topic), s.sources > 1 ? `${s.sources} outlets` : s.item.source, timeAgo(s.item.published, now)].join(' · ')}</small>
          </div>
        </a>
      ))}
      <div class="bp"><i><u style={{ width: `${(done / list.length) * 100}%` }} /></i><span>{done} of {list.length} read</span></div>
      {fact && <p class="otd"><b>On this day · {fact.year}</b>{fact.text}</p>}
    </section>
  );
}

/** A story covered by several outlets: their overlapping badges and the first names, then how many more. */
function Outlets({ outlets, total }: { outlets: string[]; total: number }) {
  const names = outlets.slice(0, 3);
  const more = total - names.length;
  return (
    <div class="src">
      <span class="stack" aria-hidden="true">
        {names.map((n) => <span key={n} class="fav" style={{ background: badgeColor(n) }}>{initial(n)}</span>)}
      </span>
      {names.join(', ')}{more > 0 ? ` +${more}` : ''}
    </div>
  );
}

/** A thin line with "N new since you last looked · time" in the middle. */
function NewDivider({ fresh, since, short }: { fresh: number; since: number; short?: boolean }) {
  return <div class="newdiv" role="separator"><span>{dividerLabel(fresh, since, undefined, short)}</span></div>;
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
  const [shown, setShown] = useState(PAGE);
  const [subShown, setSubShown] = useState(PAGE);  // rows shown in a Browse sub-topic list
  const [sportsShown, setSportsShown] = useState(PAGE);
  const [filmsShown, setFilmsShown] = useState(PAGE);
  const [localShown, setLocalShown] = useState(PAGE);  // kept here so coming back from a story finds the same rows and scroll place
  const [now, setNow] = useState(() => new Date());
  const [weather, setWeather] = useState<Weather | undefined>();
  const [kernel, setKernel] = useState<Kernel | undefined>();
  const [facts, setFacts] = useState<OnThisDay | undefined>();  // by day: a stale file just has no entry for today, so nothing shows
  const [scores, setScores] = useState<Scores | undefined>();
  const [schedule, setSchedule] = useState<Schedule | undefined>();
  const scheduleAt = useRef(0);  // when the schedule was last asked for
  const [markets, setMarkets] = useState<Markets | undefined>();
  const [marketsLoaded, setMarketsLoaded] = useState(false);
  const [earnings, setEarnings] = useState<Earnings | undefined>();
  const [settings, setSettings] = useState<Settings>(() => {
    const s = loadSettings();
    document.documentElement.style.setProperty('--read-size', `${readSize(s.textSize)}px`);  // before the first paint, so no reflow
    return s;
  });
  const [route, setRoute] = useState(() => parseRoute(location.hash));
  const scrolls = useRef<Record<string, number>>({});  // where the long list screens (home, local) were left
  const routeRef = useRef(route);
  const inAppNavs = useRef(0);  // hash changes since the app opened: more than zero means there is an app screen to go back to

  const refreshScores = () => {
    void loadScores().then((c) => { if (c) setScores(c); });  // a failed refresh keeps the last good ones
    if (Date.now() - scheduleAt.current > SCHEDULE_RECHECK_MS) {  // the file changes every few hours: no need to ask on every refresh
      scheduleAt.current = Date.now();
      void loadSchedule().then((s) => { if (s) setSchedule(s); else scheduleAt.current = 0; });
    }
  };
  const latest = useRef(0);
  const refresh = () => {
    const mine = ++latest.current;  // a slower, older response must not overwrite a newer one
    void loadWeather().then((w) => { if (w) setWeather(w); });  // independent of the feed; a failed refresh keeps the last good one
    if (routeRef.current.kind === 'sports') refreshScores();  // only the Sports tab shows them
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
    if (!key) { setMarkets(undefined); setEarnings(undefined); setMarketsLoaded(true); return; }
    void loadEarnings(key).then((e) => {
      if (mine !== latestMarkets.current) return;
      if (e) setEarnings(e);  // a failed refresh keeps the last good dates
      else if (keyNow !== undefined) setEarnings(undefined);  // ...but never another key's dates
    });
    void loadWatchlist(key).then((m) => {
      if (mine !== latestMarkets.current) return;
      if (m) setMarkets(m);  // a failed refresh keeps the last good quotes
      else if (keyNow !== undefined) setMarkets(undefined);  // ...but never another key's quotes
      setMarketsLoaded(true);
    });
  };
  const homeMarketsAt = useRef(0);
  const refreshMarketsFor = (kind: string) => {  // the home strip is not worth a request on every return to For you
    if (kind === 'home') {
      if (Date.now() - homeMarketsAt.current < HOME_MARKETS_MS) return;
      homeMarketsAt.current = Date.now();
    }
    refreshMarkets();
  };
  const day = dayKey(now);
  useEffect(() => {  // once a day: the file changes once a day, so a new local day asks again
    void loadOnThisDay().then((f) => { if (f) setFacts(f); });
  }, [day]);
  useEffect(() => {  // a few hundred bytes, asked for only when the Technology list is opened
    if (topic === 'tech') void loadKernel().then((k) => { if (k) setKernel(k); });
  }, [topic]);
  useEffect(() => {
    refresh();
    if (needsMarkets(routeRef.current.kind)) refreshMarketsFor(routeRef.current.kind);
    const onVisible = () => {
      if (document.visibilityState === 'visible') {
        setNow(new Date());
        refresh();
        if (needsMarkets(routeRef.current.kind)) refreshMarketsFor(routeRef.current.kind);
      }
    };
    document.addEventListener('visibilitychange', onVisible);
    const onHash = () => {
      const next = parseRoute(location.hash);
      const prev = routeRef.current;
      if ((prev.kind === 'home' || prev.kind === 'local' || prev.kind === 'discovery' || prev.kind === 'sports' || prev.kind === 'films') && screenKeyOf(next) !== screenKeyOf(prev)) scrolls.current[screenKeyOf(prev)] = window.scrollY;  // come back to the same place
      if (needsMarkets(next.kind)) refreshMarketsFor(next.kind);
      if (next.kind === 'sports' && routeRef.current.kind !== 'sports') refreshScores();  // fresh scores on arrival, whatever their age
      routeRef.current = next;
      inAppNavs.current += 1;
      setRoute(next);
    };
    window.addEventListener('hashchange', onHash);
    const quotes = setInterval(() => {  // quotes move every 5 minutes in market hours
      if (document.visibilityState === 'visible' && (routeRef.current.kind === 'markets' || routeRef.current.kind === 'home')) refreshMarketsFor(routeRef.current.kind);
    }, 5 * 60 * 1000);
    const live = setInterval(() => {  // the scores file is rewritten every few minutes
      if (document.visibilityState === 'visible' && routeRef.current.kind === 'sports') refreshScores();
    }, 2 * 60 * 1000);
    const tick = setInterval(() => setNow(new Date()), TICK_MS);  // "x min ago" and the stale banner keep moving
    return () => {
      latest.current = -1;
      document.removeEventListener('visibilitychange', onVisible);
      window.removeEventListener('hashchange', onHash);
      clearInterval(tick);
      clearInterval(quotes);
      clearInterval(live);
      timers.current.forEach(clearTimeout);
    };
  }, []);

  const raw = load.state === 'ready' ? load.feed : undefined;  // the Reader opens any article, even from a hidden source
  const feed = useMemo(() => (raw ? withoutSources(raw, settings.hiddenSources) : undefined), [raw, settings.hiddenSources]);
  const sources = useMemo(() => sourceNames(raw, settings.hiddenSources), [raw, settings.hiddenSources]);
  const change = (next: (prev: Settings) => Settings) => {
    setSettings((prev) => {  // from the latest state, so two quick taps both count (or cancel out, for a toggle)
      const merged = next(prev);
      saveSettings(merged);
      settingsRef.current = merged;
      return merged;
    });
  };
  const toggleWatchlist = () => change((prev) => ({ ...prev, watchCollapsed: !prev.watchCollapsed }));
  const toggleEarnings = () => change((prev) => ({ ...prev, earningsCollapsed: !prev.earningsCollapsed }));
  const toggleFollowing = (key: string) => change((prev) => ({ ...prev, following: toggleFollow(prev.following, key) }));
  const toggleKernel = () => change((prev) => ({ ...prev, kernelCollapsed: !prev.kernelCollapsed }));
  const toggleCorners = () => change((prev) => ({ ...prev, cornersCollapsed: !prev.cornersCollapsed }));
  const toggleSchedule = () => change((prev) => ({ ...prev, scheduleCollapsed: !prev.scheduleCollapsed }));
  const toggleScores = (sport: string) => change((prev) => ({ ...prev, scoresCollapsed: toggled(prev.scoresCollapsed, sport) }));
  const update = (next: Partial<Settings>) => change((prev) => ({ ...prev, ...next }));
  useEffect(() => {
    document.documentElement.style.setProperty('--read-size', `${readSize(settings.textSize)}px`);
  }, [settings.textSize]);
  const firstTeam = settings.myTeams[0];  // the theme depends on this one name, so editing another team does not rebuild it
  const theme = useMemo(() => (route.kind === 'sports' && settings.teamColors ? teamTheme(firstTeam ? [firstTeam] : []) : undefined), [route.kind, settings.teamColors, firstTeam]);
  useEffect(() => {  // the Sports tab wears the first team's colours (and the phone's status bar follows); every other screen gets the normal theme back
    const root = document.documentElement.style;
    const meta = document.querySelector('meta[name="theme-color"]');
    const normal = meta?.getAttribute('content') ?? undefined;
    if (theme) {
      for (const [name, value] of Object.entries(themeVars(theme))) root.setProperty(name, value);
      meta?.setAttribute('content', theme.bg);
    }
    return () => {
      for (const name of THEME_VARS) root.removeProperty(name);
      if (normal !== undefined) meta?.setAttribute('content', normal);
    };
  }, [theme]);
  const list = useMemo(() => (feed ? stories(feed, topic) : []), [feed, topic]);
  const lead = useMemo(() => (feed ? topStory(list, now) : undefined), [feed, list, now]);
  const full = useMemo(() => (feed && lead ? coverage(feed, lead) : []), [feed, lead]);
  const followed = useMemo(() => {
    if (!feed || topic !== 'all' || settings.following.length === 0) return [];
    const pool = [...list, ...stories(feed, 'sports'), ...stories(feed, 'entertainment'), ...stories(feed, 'science')].sort((a, b) => b.item.published.localeCompare(a.item.published));
    return followGroups(settings.following, pool, new Set(lead ? [lead.item.id] : []));
  }, [feed, list, lead, topic, settings.following]);
  const today = dayKey(now);
  const [readState, setReadState] = useState(() => ({ day: today, ids: loadRead(today) }));
  const readIds = readState.day === today ? readState.ids : loadRead(today);  // a new day starts with nothing read
  const [since, setSince] = useState(() => sinceWhen(loadLastVisit(), Date.now()));  // where "new" starts; kept for the whole sitting
  useEffect(() => {
    saveVisit(Date.now());
    let hiddenAt: number | undefined;
    const onChange = () => {
      const t = Date.now();
      if (document.visibilityState === 'hidden') {
        hiddenAt = t;
        saveVisit(t);
        return;
      }
      if (hiddenAt !== undefined && t - hiddenAt >= MIN_GAP_MS) setSince(sinceWhen(hiddenAt, t));  // a short absence is the same sitting: keep the divider where it was
      saveVisit(t);
    };
    document.addEventListener('visibilitychange', onChange);
    return () => { document.removeEventListener('visibilitychange', onChange); };
  }, []);
  const brief = useMemo(() => (topic === 'all' ? briefing(list.filter((s) => s.item.id !== lead?.item.id), now) : []), [list, lead, now, topic]);
  const rest = list.filter((s) => s.item.id !== lead?.item.id);
  const grouped = useMemo(() => (topic === 'all' ? sections(list, lead) : []), [list, lead, topic]);
  const dividerAtShown = since === undefined ? -1 : dividerAt(rest.slice(0, shown), since);  // flat list of a topic tab, newest first
  const hasLocal = feed?.items.some((i) => i.topic === 'local') ?? false;  // For You has neither local nor sports stories:
  const hasSports = feed?.items.some((i) => i.topic === 'sports') ?? false;  // point to their tabs when that is all there is
  const weatherStale = weather ? !isFresh(weather.generated, now) : false;
  const screenKey = screenKeyOf(route);
  useEffect(() => {
    window.scrollTo(0, scrolls.current[screenKey] ?? 0);
  }, [screenKey]);
  const pull = usePullToRefresh(route.kind === 'home' || route.kind === 'local' || route.kind === 'discovery' || route.kind === 'sports' || route.kind === 'films' || route.kind === 'markets', () => {
    setNow(new Date());
    if (routeRef.current.kind === 'markets') refreshMarkets();
    else {
      refresh();
      if (routeRef.current.kind === 'home') { homeMarketsAt.current = Date.now(); refreshMarkets(); }  // the strip on For you: a pull always asks
    }
  });
  const chrome = useChrome(route.kind === 'story' || route.kind === 'read', screenKey);
  const date = now.toLocaleDateString('en-US', { weekday: 'long', month: 'short', day: 'numeric' });

  if (route.kind === 'discovery') {
    return (
      <>
        <PullIndicator {...pull} />
        <DiscoveryScreen key={route.sub ?? ''} feed={feed} loaded={load.state === 'ready'} failed={load.state === 'error'} now={now} sub={route.sub}
          shown={subShown} onMore={() => setSubShown((n) => n + PAGE)} onOpenSub={() => setSubShown(PAGE)} onOpenSports={() => setSportsShown(PAGE)} following={settings.following} onFollow={toggleFollowing}
          canGoBack={inAppNavs.current > 0} cornersCollapsed={settings.cornersCollapsed} onToggleCorners={toggleCorners} onRetry={() => { setLoad({ state: 'loading' }); refresh(); }} />
        <TabBar current="discovery" />
      </>
    );
  }

  if (route.kind === 'sports') {
    return (
      <>
        <PullIndicator {...pull} />
        <SportsScreen key={route.sub ?? ''} feed={feed} scores={scores} schedule={schedule} scheduleCollapsed={settings.scheduleCollapsed} onToggleSchedule={toggleSchedule} collapsed={settings.scoresCollapsed} onFold={toggleScores} teams={settings.myTeams} loaded={load.state === 'ready'} failed={load.state === 'error'} now={now} sub={route.sub}
          shown={sportsShown} onMore={() => setSportsShown((n) => n + PAGE)} onPick={() => setSportsShown(PAGE)} following={settings.following} onFollow={toggleFollowing}
          onRetry={() => { setLoad({ state: 'loading' }); refresh(); }} />
        <TabBar current="sports" />
      </>
    );
  }

  if (route.kind === 'films') {
    return (
      <>
        <PullIndicator {...pull} />
        <FilmsScreen key={route.sub ?? ''} feed={feed} loaded={load.state === 'ready'} failed={load.state === 'error'} now={now} sub={route.sub}
          shown={filmsShown} onMore={() => setFilmsShown((n) => n + PAGE)} onPick={() => setFilmsShown(PAGE)} following={settings.following} onFollow={toggleFollowing}
          onRetry={() => { setLoad({ state: 'loading' }); refresh(); }} />
        <TabBar current="films" />
      </>
    );
  }

  if (route.kind === 'local') {
    return (
      <>
        <PullIndicator {...pull} />
        <LocalScreen feed={feed} loaded={load.state === 'ready'} failed={load.state === 'error'} weather={weather} weatherStale={weatherStale} now={now}
          shown={localShown} onMore={() => setLocalShown((n) => n + PAGE)} onRetry={() => { setLoad({ state: 'loading' }); refresh(); }} />
        <TabBar current="local" />
      </>
    );
  }

  if (route.kind === 'markets') {
    return (
      <>
        <PullIndicator {...pull} />
        <MarketsScreen markets={markets} earnings={earnings} earnCollapsed={settings.earningsCollapsed} onToggleEarn={toggleEarnings} hasKey={settings.watchKey !== ''} loaded={marketsLoaded} now={now} hidden={settings.hiddenTickers}
          collapsed={settings.watchCollapsed} onToggle={toggleWatchlist}
          feed={feed} onAllBusiness={() => { setTopic('business'); location.hash = '#'; }} />
        <TabBar current="markets" />
      </>
    );
  }

  if (route.kind === 'quote') {
    return (
      <>
        <QuoteScreen key={route.id} markets={markets} earnings={earnings} loaded={marketsLoaded} symbol={route.id} now={now} canGoBack={inAppNavs.current > 0} />
        <TabBar current="markets" />
      </>
    );
  }

  if (route.kind === 'settings') {
    return (
      <>
        <SettingsScreen settings={settings} update={update} sources={sources} suggestions={teamSuggestions(scores)} markets={markets} marketsLoaded={marketsLoaded}
          onSaved={(key) => afterSave(key)} canGoBack={inAppNavs.current > 0} />
        <TabBar current={null} />
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
            <div class="e">{date}</div>
            <h1>{topic === 'all' ? 'For you' : topicLabel(topic)}</h1>
          </div>
          <SettingsLink />
        </header>
        <nav class="chips" aria-label="Topics">
          {TOPICS.map((t) => (
            <button key={t.id} type="button" class={t.id === topic ? 'on' : ''} aria-pressed={t.id === topic}
              onClick={() => { setTopic(t.id); setShown(PAGE); }}>
              {t.label}
            </button>
          ))}
        </nav>

        {load.state === 'loading' && <p class="note">Loading the latest stories…</p>}
        {load.state === 'error' && (
          <div class="empty"><b>Can't load the news</b><span>Check your connection.</span>
            <button type="button" class="btn" onClick={() => { setLoad({ state: 'loading' }); refresh(); }}>Try again</button></div>
        )}
        {feed && isStale(feed.generated, now) && <p class="note warn">Updated {timeAgo(feed.generated, now)}; newer stories may be missing.</p>}
        {raw && feed && raw.items.length > 0 && feed.items.length === 0 && <div class="empty"><b>All sources are hidden</b><span>Turn some back on in Settings.</span><a class="btn" href="#/settings">Open Settings</a></div>}
        {feed && list.length === 0 && feed.items.length > 0 && <div class="empty"><b>Nothing here yet</b><span>No recent stories in this topic.{hasLocal && <> Local stories are in the <a href="#/local">Local tab</a>.</>}{hasSports && <> Sports stories are in the <a href="#/sports">Sports tab</a>.</>}</span></div>}
        {feed && list.length === 0 && raw?.items.length === 0 && <div class="empty"><b>Nothing here yet</b><span>No recent stories in this topic.</span></div>}

        {topic === 'tech' && kernel && kernelFresh(kernel.generated, now) && <KernelTable kernel={kernel} collapsed={settings.kernelCollapsed} onToggle={toggleKernel} />}
        {topic === 'all' && weather && <WeatherStrip weather={weather} stale={weatherStale} now={now} />}
        {topic === 'all' && <MarketsStrip markets={markets} earnings={earnings} hidden={settings.hiddenTickers} now={now} />}
        {topic === 'all' && <Briefing stories={brief} read={readIds} onOpen={(id) => setReadState({ day: today, ids: markRead(today, id) })} now={now} fact={factFor(facts, today)} />}

        {lead && (
          <>
            <div class="sec"><b>Top story</b></div>
            <StoryAnchor story={lead} class="topcard">
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

        {topic === 'all' && <FollowingSection groups={followed} now={now} />}
        {topic !== 'all' && weather && <WeatherStrip weather={weather} stale={weatherStale} now={now} />}
        {topic === 'all' && grouped.map((g) => (
          <TopicSection key={g.topic} section={g} now={now} since={since} onAll={() => { setTopic(g.topic); setShown(PAGE); window.scrollTo(0, 0); }} />
        ))}
        {topic !== 'all' && rest.slice(0, shown).map((s, n) => (
          <Fragment key={s.item.id}>
            {n === dividerAtShown && since !== undefined && <NewDivider fresh={n} since={since} />}
            <StoryRow s={s} now={now} />
          </Fragment>
        ))}
        {topic !== 'all' && rest.length > shown && (
          <div class="more"><button type="button" class="btn g" onClick={() => setShown((n) => n + PAGE)}>Show more</button></div>
        )}
      </div>
      <PullIndicator {...pull} />
      <TabBar />
    </>
  );
}
