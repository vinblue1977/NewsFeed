import { useEffect, useMemo, useRef, useState } from 'preact/hooks';

import { loadFeed } from './api';
import { badgeColor, coverage, initial, isStale, safeUrl, stories, timeAgo, TOPICS, topicLabel, topStory } from './feed';
import type { Feed, Topic } from './types';

const PAGE = 30;
const TICK_MS = 60_000;

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
  const list = useMemo(() => (feed ? stories(feed, topic) : []), [feed, topic]);
  const lead = useMemo(() => (feed ? topStory(list, now) : undefined), [feed, list, now]);
  const full = useMemo(() => (feed && lead ? coverage(feed, lead) : []), [feed, lead]);
  const rest = list.filter((s) => s.item.id !== lead?.item.id);
  const date = now.toLocaleDateString('en-US', { weekday: 'long', month: 'short', day: 'numeric' });

  return (
    <>
      <div class="wrap">
        <header class="hdr">
          <div class="e">{date}</div>
          <h1>{topic === 'all' ? 'For you' : topicLabel(topic)}</h1>
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
        {feed && list.length === 0 && <div class="empty"><b>Nothing here yet</b><span>No recent stories in this topic.</span></div>}

        {lead && (
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

        {rest.slice(0, shown).map((s) => (
          <a class="row" key={s.item.id} href={safeUrl(s.item.url)} target="_blank" rel="noopener noreferrer">
            <div class="t">
              <Source name={s.item.source} when={timeAgo(s.item.published, now)}
                extra={[topicLabel(s.item.topic), s.item.place, s.sources > 1 ? `${s.sources} sources` : ''].filter(Boolean).join(' · ')} />
              <h3>{s.item.title}</h3>
            </div>
          </a>
        ))}
        {rest.length > shown && (
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
