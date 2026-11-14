import { useEffect, useMemo, useRef, useState } from 'preact/hooks';

import { loadFeed } from './api';
import { badgeColor, BRIEF_TOP_COLOR, briefing, coverage, initial, isStale, safeUrl, stories, timeAgo, TOPICS, topicLabel, topStory } from './feed';
import type { Feed, Topic } from './types';

const PAGE = 30;
const TICK_MS = 60_000;
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

  const latest = useRef(0);
  const refresh = () => {
    const mine = ++latest.current;  // a slower, older response must not overwrite a newer one
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
    const tick = setInterval(() => setNow(new Date()), TICK_MS);  // "x min ago" and the stale banner keep moving
    return () => {
      latest.current = -1;
      document.removeEventListener('visibilitychange', onVisible);
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
  const date = now.toLocaleDateString('en-US', { weekday: 'long', month: 'short', day: 'numeric' });

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
            {brief.top && (
              <>
                <div class="grp"><i style={{ background: BRIEF_TOP_COLOR }} />Top story</div>
                <a class="bi first" href={safeUrl(brief.top.item.url)} target="_blank" rel="noopener noreferrer">
                  <h2>{brief.top.item.title}</h2>
                  {brief.top.item.summary && <p>{brief.top.item.summary.slice(0, 200)}</p>}
                  <div class="m"><span>{brief.top.item.source}</span><span>{timeAgo(brief.top.item.published, now)}</span>
                    {brief.top.sources > 1 && <span class="c">{brief.top.sources} sources</span>}</div>
                </a>
              </>
            )}
            {brief.groups.map((g) => (
              <section key={g.label}>
                <div class="grp"><i style={{ background: g.color }} />{g.label}</div>
                {g.stories.map((st) => (
                  <a class="bi" key={st.item.id} href={safeUrl(st.item.url)} target="_blank" rel="noopener noreferrer">
                    <h2>{st.item.title}</h2>
                    <div class="m"><span>{st.item.source}</span><span>{timeAgo(st.item.published, now)}</span></div>
                  </a>
                ))}
              </section>
            ))}
            {brief.total > 0 && <div class="done">You're all caught up ✓</div>}
          </>
        )}

        {!isBrief && lead && (
          <>
            <div class="sec"><b>Top story</b></div>
            <a class="big" href={safeUrl(lead.item.url)} target="_blank" rel="noopener noreferrer">
              <Source name={lead.item.source} when={timeAgo(lead.item.published, now)} />
              <h2>{lead.item.title}</h2>
            </a>
            {full.length > 0 && (
              <div class="full">
                <div class="lab">FULL COVERAGE · {lead.sources} SOURCES</div>
                {full.map((i) => (
                  <a class="it" key={i.id} href={safeUrl(i.url)} target="_blank" rel="noopener noreferrer">
                    <Source name={i.source} when={timeAgo(i.published, now)} />
                    <b>{i.title}</b>
                  </a>
                ))}
              </div>
            )}
          </>
        )}

        {!isBrief && rest.slice(0, shown).map((s) => (
          <a class="row" key={s.item.id} href={safeUrl(s.item.url)} target="_blank" rel="noopener noreferrer">
            <div class="t">
              <Source name={s.item.source} when={timeAgo(s.item.published, now)}
                extra={[topicLabel(s.item.topic), s.item.place, s.sources > 1 ? `${s.sources} sources` : ''].filter(Boolean).join(' · ')} />
              <h3>{s.item.title}</h3>
            </div>
          </a>
        ))}
        {!isBrief && rest.length > shown && (
          <div class="more"><button type="button" class="btn g" onClick={() => setShown((n) => n + PAGE)}>Show more</button></div>
        )}
      </div>
      <nav class="tabbar" aria-label="Sections">
        <button type="button" class="on" aria-current="page">For you</button>
        {['Explore', 'Saved', 'Markets', 'Settings'].map((name) => (
          <button key={name} type="button" disabled>{name}</button>
        ))}
      </nav>
    </>
  );
}
