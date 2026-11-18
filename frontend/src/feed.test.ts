import { describe, expect, it } from 'vitest';

import { TOPICS, badgeColor, imageSrc, sections, subtopicsOf, subtopicRoute, coverage, initial, parseFeed, parseRoute, readerPage, storyLink, storyPage, isStale, safeUrl, splitRecent, discovery, sportSections, teamStories, byBreaking, mixSources, subtopicOf, subtopicLabel, stories, timeAgo, topicLabel, topStory } from './feed';
import type { Feed, Item } from './types';

const NOW = new Date('2026-11-13T12:00:00Z');
const item = (id: string, over: Partial<Item> = {}): Item => ({
  id, title: `T${id}`, url: `https://e.com/${id}`, summary: '', published: '2026-11-13T11:00:00+00:00', source: `S${id}`, topic: 'us', ...over,
});
const feed: Feed = {
  generated: '2026-11-13T11:50:00+00:00',
  items: [
    item('a', { cluster: 'c1', published: '2026-11-13T10:00:00+00:00' }),
    item('b', { cluster: 'c1', published: '2026-11-13T10:30:00+00:00' }),
    item('c', { cluster: 'c1', source: 'Sa' }),
    item('d', { topic: 'world', published: '2026-11-13T11:30:00+00:00' }),
    item('e', { topic: 'tech', cluster: 'c2', published: '2026-11-10T11:30:00+00:00' }),
  ],
  clusters: [
    { id: 'c1', title: 'x', topic: 'us', lead: 'a', published: '', sources: 3, items: ['a', 'b', 'c', 'zz'] },
    { id: 'c2', title: 'y', topic: 'tech', lead: 'e', published: '', sources: 1, items: ['e'] },
  ],
};

describe('feed helpers', () => {
  it('formats relative time', () => {
    expect(timeAgo('2026-11-13T11:59:50Z', NOW)).toBe('1 min ago');
    expect(timeAgo('2026-11-13T11:15:00Z', NOW)).toBe('45 min ago');
    expect(timeAgo('2026-11-13T11:00:10Z', NOW)).toBe('59 min ago');
    expect(timeAgo('2026-11-13T10:30:00Z', NOW)).toBe('1 h ago');
    expect(timeAgo('2026-11-12T12:20:00Z', NOW)).toBe('23 h ago');
    expect(timeAgo('2026-11-13T09:00:00Z', NOW)).toBe('3 h ago');
    expect(timeAgo('2026-11-10T12:00:00Z', NOW)).toBe('3 d ago');
    expect(timeAgo('2026-11-14T12:00:00Z', NOW)).toBe('1 min ago');
    expect(timeAgo('nonsense', NOW)).toBe('');
  });

  it('only links to web URLs', () => {
    expect(safeUrl('https://e.com/x')).toBe('https://e.com/x');
    expect(safeUrl(['java', 'script:alert(1)'].join(''))).toBe('#');
    expect(safeUrl('not a url')).toBe('#');
  });

  it('detects a stale feed', () => {
    expect(isStale('2026-11-13T11:00:00Z', NOW)).toBe(false);
    expect(isStale('2026-11-13T08:00:00Z', NOW)).toBe(true);
  });

  it('labels, badges and validates', () => {
    expect(topicLabel('tech')).toBe('Technology');
    expect(topicLabel('zzz')).toBe('zzz');
    expect(badgeColor('NPR')).toBe(badgeColor('NPR'));
    expect(initial(' npr')).toBe('N');
    expect(initial('')).toBe('?');
    expect(parseFeed(feed)?.items).toHaveLength(5);
    expect(parseFeed({ items: [] })).toBeUndefined();
    expect(parseFeed(null)).toBeUndefined();
  });

  it('drops malformed items and clusters instead of failing', () => {
    const bad = { ...feed, items: [...feed.items, { id: 'x' }, null, { ...feed.items[0], source: null }], clusters: [...feed.clusters, { id: 'k' }, 7] };
    const parsed = parseFeed(bad);
    expect(parsed?.items).toHaveLength(5);
    expect(parsed?.clusters).toHaveLength(2);
  });

  it('shows one story per cluster, newest first, filtered by topic', () => {
    expect(stories(feed, 'all').map((s) => s.item.id)).toEqual(['d', 'a', 'e']);
    expect(stories(feed, 'world').map((s) => s.item.id)).toEqual(['d']);
    expect(stories(feed, 'us')[0]?.sources).toBe(3);
  });

  it('falls back to another member when the lead is missing or in another topic', () => {
    const noLead: Feed = { ...feed, items: feed.items.filter((i) => i.id !== 'a') };
    expect(stories(noLead, 'us').map((s) => s.item.id)).toEqual(['c']);
    const mixed: Feed = { ...feed, items: feed.items.map((i) => (i.id === 'a' ? { ...i, topic: 'world' as const } : i)) };
    expect(stories(mixed, 'us').map((s) => s.item.id)).toEqual(['c']);
    const unknown: Feed = { ...feed, clusters: [] };
    expect(stories(unknown, 'all').map((s) => s.item.id)).toEqual(['d', 'c', 'e']);
  });

  it('picks the best-covered recent story as the lead', () => {
    const list = stories(feed, 'all');
    expect(topStory(list, NOW)?.item.id).toBe('a');
    expect(topStory(stories(feed, 'tech'), NOW)).toBeUndefined();
  });

  it('only picks a lead from the last 24 hours: not an old, future-dated or unreadable story', () => {
    const at = (id: string, published: string) => ({ item: item(id, { published }), cluster: undefined, sources: 1 });
    expect(topStory([at('bad', 'sometime yesterday'), at('old', '2026-11-12T11:59:59+00:00')], NOW)).toBeUndefined();
    expect(topStory([at('edge', '2026-11-12T12:00:01+00:00')], NOW)?.item.id).toBe('edge');
    expect(topStory([at('future', '2026-11-14T09:00:00+00:00')], NOW)?.item.id).toBe('future');  // a clock slip counts as just now
  });

  it('a news tab lists only the stories that belong to it: a story with members in two topics shows in one tab', () => {
    const two: Feed = {
      generated: '2026-11-13T11:50:00+00:00',
      items: [item('w', { topic: 'world', cluster: 'cx' }), item('t', { topic: 'tech', cluster: 'cx' }), item('u', { topic: 'tech' })],
      clusters: [{ id: 'cx', title: 'X', topic: 'world', lead: 'w', published: '2026-11-13T11:00:00+00:00', sources: 2, items: ['w', 't'] }],
    };
    expect(stories(two, 'world').map((s) => s.item.id)).toEqual(['w']);
    expect(stories(two, 'tech').map((s) => s.item.id)).toEqual(['u']);  // not the world story's tech member
    expect(stories(two, 'all').map((s) => s.item.id).sort()).toEqual(['u', 'w']);
  });

  it('lists coverage from other sources only', () => {
    const lead = stories(feed, 'us')[0];
    if (!lead) throw new Error('no lead');
    expect(coverage(feed, lead).map((i) => i.id)).toEqual(['b']);
    expect(coverage(feed, { item: item('q'), cluster: undefined, sources: 1 })).toEqual([]);
  });

  it('reads the route from the URL hash', () => {
    expect(parseRoute('#/local')).toEqual({ kind: 'local' });
    expect(parseRoute('#/discovery')).toEqual({ kind: 'discovery' });
    expect(parseRoute('#/sports')).toEqual({ kind: 'sports' });
    expect(parseRoute('#/sports/nba')).toEqual({ kind: 'sports', sub: 'nba' });
    expect(parseRoute('#/sports/NBA!')).toEqual({ kind: 'home' });
    expect(parseRoute('#/discovery/cricket')).toEqual({ kind: 'discovery', sub: 'cricket' });
    expect(parseRoute('#/discovery/Bad Thing')).toEqual({ kind: 'home' });
    expect(parseRoute('#/markets')).toEqual({ kind: 'markets' });
    expect(parseRoute('#/settings')).toEqual({ kind: 'settings' });
    expect(parseRoute('#/quote/NVDA')).toEqual({ kind: 'quote', id: 'NVDA' });
    expect(parseRoute('#/quote/%5EGSPC')).toEqual({ kind: 'quote', id: '^GSPC' });
    for (const bad of ['#/quote/', '#/quote/has space', '#/quote/%E0%A4%A', '#/quote/' + 'A'.repeat(41)]) expect(parseRoute(bad)).toEqual({ kind: 'home' });
    expect(parseRoute('#/markets/x')).toEqual({ kind: 'home' });
    expect(parseRoute('')).toEqual({ kind: 'home' });
    expect(parseRoute('#')).toEqual({ kind: 'home' });
    expect(parseRoute('#/story/c1')).toEqual({ kind: 'story', id: 'c1' });
    expect(parseRoute('#/story/')).toEqual({ kind: 'home' });
    expect(parseRoute('#/story/a/b')).toEqual({ kind: 'home' });
    expect(parseRoute('#/story/<script>')).toEqual({ kind: 'home' });
    expect(parseRoute('#/read/abc_1')).toEqual({ kind: 'read', id: 'abc_1' });
    expect(parseRoute('#/read/a b')).toEqual({ kind: 'home' });
    expect(parseRoute('#/other/abc')).toEqual({ kind: 'home' });
  });

  it('links a multi-source story to its screen and a single-source one to the Reader', () => {
    const [multi] = stories(feed, 'us');
    if (!multi) throw new Error('no story');
    expect(storyLink(multi)).toBe('#/story/c1');
    expect(storyLink({ item: item('x'), cluster: undefined, sources: 1 })).toBe('#/read/x');
    expect(storyLink({ item: item('y'), cluster: feed.clusters[1], sources: 1 })).toBe('#/read/y');
  });

  it('builds the Reader page, linking to full coverage only when several sources are present', () => {
    expect(readerPage(feed, 'a')).toEqual({ item: feed.items[0], coverageId: 'c1' });
    expect(readerPage(feed, 'e')?.coverageId).toBeUndefined();  // a cluster of one
    expect(readerPage(feed, 'd')?.coverageId).toBeUndefined();  // not clustered
    const oneSource: Feed = { ...feed, items: feed.items.map((i) => (i.cluster === 'c1' ? { ...i, source: 'same' } : i)) };
    expect(readerPage(oneSource, 'a')?.coverageId).toBeUndefined();  // the cluster's other articles are from the same source
    expect(readerPage(feed, 'nope')).toBeUndefined();
  });

  it('builds the story page: cluster articles newest first, and related stories from the topic', () => {
    const page = storyPage(feed, 'c1');
    expect(page?.items.map((i) => i.id)).toEqual(['c', 'b', 'a']);
    expect(page?.related).toEqual([]);
    expect(page?.sources).toBe(2);  // the cluster says 3, but the articles present come from only 2 distinct sources
    const more: Feed = { ...feed, items: [...feed.items, item('r1'), item('r2', { published: '2026-11-13T09:00:00+00:00' })] };
    expect(storyPage(more, 'c1', 1)?.related.map((s) => s.item.id)).toEqual(['r1']);
    expect(storyPage(feed, 'nope')).toBeUndefined();
    expect(storyPage({ ...feed, items: [] }, 'c1')).toBeUndefined();
  });
});

describe('pictures and sections', () => {
  const NAME = 'a1b2c3d4e5f60718.jpg';
  it('serves a picture only from our own site and only for names the ingest writes', () => {
    expect(imageSrc(item('x', { img: NAME }))).toBe(`/data/img/${NAME}`);
    for (const bad of ['../x.jpg', 'https://evil.example/a.jpg', 'A1B2C3D4E5F60718.jpg', 'a1b2c3d4e5f60718.svg', '']) {
      expect(imageSrc(item('x', { img: bad }))).toBeUndefined();
    }
    expect(imageSrc(item('x'))).toBeUndefined();
    expect(imageSrc(item('x', { img: 5 as unknown as string }))).toBeUndefined();
  });

  const story = (id: string, topic: Item['topic'], over: Partial<Item> = {}) => ({ item: item(id, { topic, ...over }), cluster: undefined, sources: 1 });
  it('groups by topic in a fixed order; the lead prefers a story with a picture; the top story is left out', () => {
    const list = [
      story('w1', 'world'), story('u1', 'us'), story('u2', 'us', { img: NAME }), story('u3', 'us'), story('u4', 'us'),
      story('top', 'tech'), story('t1', 'tech'),
    ];
    const out = sections(list, list[5]);
    expect(out.map((s) => s.topic)).toEqual(['us', 'world', 'tech']);
    const us = out[0];
    expect(us?.lead.item.id).toBe('u2');  // the one with a picture
    expect(us?.more.map((s) => s.item.id)).toEqual(['u1', 'u3']);  // then the newest others, two at most
    expect(us?.total).toBe(4);
    expect(out[2]?.lead.item.id).toBe('t1');
  });
  it('leaves out a topic with nothing and the whole cluster of the top story', () => {
    const c = { id: 'c', title: '', topic: 'us' as const, lead: 'a', published: '', sources: 2, items: [] };
    const a = { item: item('a'), cluster: c, sources: 2 };
    const b = { item: item('b'), cluster: c, sources: 2 };
    expect(sections([a, b], a)).toEqual([]);
    expect(sections([], undefined)).toEqual([]);
  });
});

describe('splitRecent', () => {
  const now = new Date('2026-11-15T12:00:00Z');
  const story = (id: string, published: string) => ({ item: { id, title: id, url: 'https://x.test', summary: '', published, source: 's', topic: 'local' as const }, cluster: undefined, sources: 1 });
  it('puts the last 24 hours first and everything else, including bad dates, under earlier', () => {
    const list = [story('a', '2026-11-15T10:00:00Z'), story('b', '2026-11-14T13:00:00Z'), story('c', '2026-11-14T11:00:00Z'), story('d', 'garbage')];
    const { recent, earlier } = splitRecent(list, now);
    expect(recent.map((s) => s.item.id)).toEqual(['a', 'b']);
    expect(earlier.map((s) => s.item.id)).toEqual(['c', 'd']);
    expect(splitRecent([story('bad', 'garbage'), story('old', '2026-11-01T00:00:00Z')], now).earlier.map((s) => s.item.id)).toEqual(['old', 'bad']);  // bad dates last
  });
});

describe('discovery', () => {
  const now = new Date('2026-11-15T12:00:00Z');
  const mk = (id: string, published: string, sources: number, subtopic?: string) => ({
    item: { id, title: id, url: 'https://x.test', summary: '', published, source: 's', topic: 'us' as const, subtopic },
    cluster: sources > 1 ? { id: `c-${id}`, title: id, topic: 'us' as const, lead: id, published, sources, items: [id] } : undefined,
    sources,
  });
  const list = [  // newest first
    mk('new1', '2026-11-15T11:50:00Z', 1, 'cricket'), mk('wide3', '2026-11-15T10:00:00Z', 3), mk('wide7', '2026-11-15T09:00:00Z', 7),
    mk('top', '2026-11-15T08:00:00Z', 12, 'cricket'), mk('nfl1', '2026-11-14T08:00:00Z', 1, 'nfl'), mk('old', '2026-11-10T08:00:00Z', 9, 'cricket'),
  ];
  it('ranks widely covered stories by sources, leaves out the top story, and keeps Just in to the last day', () => {
    const d = discovery(list, now);
    expect(d.widely.map((s) => s.item.id)).toEqual(['wide7', 'wide3']);
    expect(d.justIn.map((s) => s.item.id)).toEqual(['new1']);
    expect(discovery([mk('old', '2026-11-01T00:00:00Z', 1)], now).justIn).toEqual([]);
  });
  it('counts every story of a sub-topic, top story included, so a tile matches the list it opens', () => {
    expect(discovery(list, now).corners.map((c) => [c.id, c.lead.item.id, c.total])).toEqual([['cricket', 'new1', 3], ['nfl', 'nfl1', 1]]);
    expect(discovery([], now)).toEqual({ widely: [], justIn: [], corners: [] });
  });
  it('titles sub-topics', () => {
    expect([subtopicLabel('cricket'), subtopicLabel('nfl'), subtopicLabel('f1'), subtopicLabel('soccer')]).toEqual(['Cricket', 'NFL', 'F1', 'Soccer']);
  });
});

describe('tab-only topics stay out of For You', () => {
  const item = (id: string, topic: 'us' | 'local' | 'sports', cluster?: string) => ({ id, title: id, url: 'https://x.test', summary: '', published: '2026-11-15T10:00:00Z', source: 's', topic, cluster });
  const feed = {
    generated: '2026-11-15T11:30:00Z',
    items: [item('a', 'us'), item('sp1', 'sports'), item('l1', 'local'), item('l2', 'local', 'c1'), item('l3', 'local', 'c1')],
    clusters: [{ id: 'c1', title: 'Local cluster', topic: 'local' as const, lead: 'l2', published: '2026-11-15T10:00:00Z', sources: 2, items: ['l2', 'l3'] }],
  };
  it('leaves local out of "all" but still returns it for the local topic', () => {
    expect(stories(feed, 'all').map((s) => s.item.id)).toEqual(['a']);
    expect(stories(feed, 'local').map((s) => s.item.id).sort()).toEqual(['l1', 'l2']);
    expect(stories(feed, 'sports').map((s) => s.item.id)).toEqual(['sp1']);
  });
  it('keeps a local cluster out of For You even when a non-local story joined it', () => {
    const mixed = { ...feed, items: [...feed.items, item('u', 'us', 'c1')] };
    expect(stories(mixed, 'all').map((s) => s.item.id)).toEqual(['a']);
  });
  it('has no Local or Sports topic chip or section, and still labels their stories', () => {
    expect(TOPICS.map((t) => t.id)).not.toContain('local');
    expect(TOPICS.map((t) => t.id)).not.toContain('sports');
    expect(topicLabel('sports')).toBe('Sports');
    expect(topicLabel('local')).toBe('Local');
    expect(sections(stories(feed, 'all'), undefined).map((s) => s.topic)).not.toContain('local');
  });
});

describe('sports tab helpers', () => {
  const mk = (id: string, subtopic?: string) => ({ item: { id, title: id, url: 'https://x.test', summary: '', published: '2026-11-15T10:00:00Z', source: 's', topic: 'sports' as const, subtopic }, cluster: undefined, sources: 1 });
  it('orders sub-topics by story count and ignores untagged stories', () => {
    expect(subtopicsOf([mk('a', 'nfl'), mk('b', 'soccer'), mk('c', 'soccer'), mk('d')])).toEqual(['soccer', 'nfl']);
    expect(subtopicsOf([])).toEqual([]);
  });
  it('merges a sub-topic across both lists, keeps the newest as its lead, and keeps topics apart', () => {
    const now = new Date('2026-11-15T12:00:00Z');
    const biz = { ...mk('b', 'markets'), item: { ...mk('b', 'markets').item, topic: 'business' as const, published: '2026-11-15T09:00:00Z' } };
    const newer = { ...mk('n', 'nfl'), item: { ...mk('n', 'nfl').item, published: '2026-11-15T11:00:00Z' } };
    const corners = discovery([biz, mk('x', 'markets')], now, [mk('a', 'nfl'), newer]).corners;
    expect(corners.map((c) => [c.topic, c.id, c.total, c.lead.item.id])).toEqual([['sports', 'nfl', 2, 'n'], ['sports', 'markets', 1, 'x'], ['business', 'markets', 1, 'b']]);
    expect(subtopicRoute('sports', 'nfl')).toBe('#/sports/nfl');
    expect(subtopicRoute('business', 'markets')).toBe('#/discovery/markets');
  });
  it('lets Browse count sports tiles and send them to the Sports tab', () => {
    const now = new Date('2026-11-15T12:00:00Z');
    const corners = discovery([], now, [mk('a', 'nfl'), mk('b', 'nfl')]).corners;
    expect(corners.map((c) => [c.id, c.topic, c.total])).toEqual([['nfl', 'sports', 2]]);
  });
});

describe('sportSections', () => {
  const mk = (id: string, subtopic?: string, img?: string) => ({ item: { id, title: id, url: 'https://x.test', summary: '', published: '2026-11-15T10:00:00Z', source: 's', topic: 'sports' as const, subtopic, img }, cluster: undefined, sources: 1 });
  it('makes a section per sport, most stories first, led by a story with a picture', () => {
    const got = sportSections([mk('c1', 'cricket'), mk('n1', 'nfl'), mk('n2', 'nfl', '0123456789abcdef.jpg'), mk('n3', 'nfl'), mk('n4', 'nfl'), mk('x')]);
    expect(got.map((g) => [g.sub, g.label, g.lead.item.id, g.more.map((m) => m.item.id), g.total])).toEqual([
      ['nfl', 'NFL', 'n2', ['n1', 'n3'], 4],
      ['cricket', 'Cricket', 'c1', [], 1],
    ]);
  });
  it('gives an unknown sport a colour and no sections for no stories', () => {
    expect(sportSections([mk('a', 'curling')])[0]?.color).toMatch(/^#/);
    expect(sportSections([])).toEqual([]);
  });
});

describe('teamStories', () => {
  const mk = (id: string, title: string) => ({ item: { id, title, url: 'https://x.test', summary: '', published: '2026-11-15T10:00:00Z', source: 's', topic: 'sports' as const }, cluster: undefined, sources: 1 });
  it('keeps the stories whose headline names a followed team, in order', () => {
    const list = [mk('a', 'Bears rally late'), mk('b', 'Lions win'), mk('c', 'Why the bears hibernate')];
    expect(teamStories(list, (t) => /bears/i.test(t)).map((s) => s.item.id)).toEqual(['a', 'c']);
    expect(teamStories(list, null)).toEqual([]);
  });
});

describe('byBreaking', () => {
  const now = new Date('2026-11-16T12:00:00Z');
  const mk = (id: string, published: string, sources = 1) => ({ item: { id, title: id, url: 'https://x.test', summary: '', published, source: 's', topic: 'sports' as const }, cluster: undefined, sources });
  const hoursAgo = (h: number) => new Date(now.getTime() - h * 3600_000).toISOString();
  const ids = (list: ReturnType<typeof mk>[]) => byBreaking(list, now).map((s) => s.item.id);

  it('keeps plain newest-first order when every story has one source', () => {
    expect(ids([mk('old', hoursAgo(5)), mk('new', hoursAgo(1)), mk('mid', hoursAgo(3))])).toEqual(['new', 'mid', 'old']);
  });

  it('lifts a widely covered story, a little less the older it is', () => {
    // covered3 (4h old, 2 extra sources) ranks about 0.7h ago and covered2 (2.5h old, 1 extra) about 0.7h ago: both above the 1h story
    expect(ids([mk('fresh', hoursAgo(1)), mk('covered3', hoursAgo(4), 3), mk('covered2', hoursAgo(2.5), 2)])).toEqual(['covered3', 'covered2', 'fresh']);
  });

  it('caps the lift at three extra sources and gives a day-old story none', () => {
    // huge (10h, 9 sources) ranks as 10h - 3.5h = 6.5h ago: behind the 3h story. The two over a day old have no lift.
    expect(ids([mk('huge', hoursAgo(10), 9), mk('new', hoursAgo(3)), mk('stale', hoursAgo(30), 4), mk('newer', hoursAgo(29))])).toEqual(['new', 'huge', 'newer', 'stale']);
  });

  it('fades smoothly: a story does not jump when it reaches a day old', () => {
    const before = ids([mk('wide', hoursAgo(23.9), 5), mk('b', hoursAgo(20))]);
    const after = ids([mk('wide', hoursAgo(24.1), 5), mk('b', hoursAgo(20))]);
    expect(before).toEqual(['b', 'wide']);
    expect(after).toEqual(before);  // no change across the 24 hour mark
  });

  it('treats a future date as just now and a bad source count as one source', () => {
    expect(ids([mk('now', hoursAgo(0.5)), mk('future', new Date(now.getTime() + 3600_000).toISOString())])).toEqual(['future', 'now']);
    const odd = [mk('nan', hoursAgo(2), Number.NaN), mk('inf', hoursAgo(3), Number.POSITIVE_INFINITY), mk('neg', hoursAgo(4), -3), mk('one', hoursAgo(1))];
    expect(ids(odd)).toEqual(['one', 'nan', 'inf', 'neg']);
  });

  it('sorts an unreadable date last, keeps input order on ties, and does not change the input', () => {
    const list = [mk('bad1', 'not a date', 3), mk('ok', hoursAgo(2)), mk('bad2', 'also bad')];
    const copy = [...list];
    expect(ids(list)).toEqual(['ok', 'bad1', 'bad2']);
    expect(list).toEqual(copy);
    expect(byBreaking([], now)).toEqual([]);
  });
});

describe('mixSources', () => {
  const mk = (id: string, source: string) => ({ item: { id, title: id, url: 'https://x.test', summary: '', published: '2026-11-16T10:00:00Z', source, topic: 'sports' as const }, cluster: undefined, sources: 1 });
  const ids = (list: ReturnType<typeof mk>[]) => mixSources(list).map((s) => s.item.id);

  it('breaks a long run from one source with the next story of another', () => {
    const list = [mk('e1', 'ESPN'), mk('e2', 'ESPN'), mk('e3', 'ESPN'), mk('e4', 'ESPN'), mk('n1', 'NFL.com'), mk('n2', 'NFL.com')];
    expect(ids(list)).toEqual(['e1', 'e2', 'n1', 'e3', 'e4', 'n2']);
  });

  it('keeps each source in its own order and drops nothing', () => {
    const list = [mk('e1', 'ESPN'), mk('e2', 'ESPN'), mk('e3', 'ESPN'), mk('n1', 'NFL.com'), mk('n2', 'NFL.com'), mk('n3', 'NFL.com'), mk('e4', 'ESPN')];
    const got = ids(list);
    expect([...got].sort()).toEqual(['e1', 'e2', 'e3', 'e4', 'n1', 'n2', 'n3']);
    expect(got.filter((i) => i.startsWith('e'))).toEqual(['e1', 'e2', 'e3', 'e4']);
    expect(got.filter((i) => i.startsWith('n'))).toEqual(['n1', 'n2', 'n3']);
    expect(got).toEqual(['e1', 'e2', 'n1', 'e3', 'n2', 'n3', 'e4']);
  });

  it('leaves the order alone when sources already alternate, when there is one source, and for an empty list', () => {
    const alternating = [mk('e1', 'ESPN'), mk('n1', 'NFL.com'), mk('e2', 'ESPN'), mk('n2', 'NFL.com')];
    expect(ids(alternating)).toEqual(['e1', 'n1', 'e2', 'n2']);
    const one = [mk('a', 'ESPN'), mk('b', 'ESPN'), mk('c', 'ESPN'), mk('d', 'ESPN')];
    expect(ids(one)).toEqual(['a', 'b', 'c', 'd']);
    expect(mixSources([])).toEqual([]);
  });

  it('only reaches for another source within the look-ahead', () => {
    const far = [...Array.from({ length: 10 }, (_, i) => mk('e' + i, 'ESPN')), mk('n1', 'NFL.com')];
    // n1 is 11th: it is out of reach until the ESPN run has been taken down far enough, then it is pulled in
    expect(ids(far)).toEqual(['e0', 'e1', 'e2', 'n1', 'e3', 'e4', 'e5', 'e6', 'e7', 'e8', 'e9']);
    const veryFar = [...Array.from({ length: 30 }, (_, i) => mk('e' + i, 'ESPN')), mk('n1', 'NFL.com')];
    expect(ids(veryFar).indexOf('n1')).toBe(23);  // 30 + 1 stories: pulled in once it is within 8 places
  });

  it('never moves a widely covered story or counts it towards a run', () => {
    const wide = { ...mk('w', 'ESPN'), sources: 3 };
    const list = [mk('e1', 'ESPN'), mk('e2', 'ESPN'), wide, mk('e3', 'ESPN'), mk('n1', 'NFL.com')];
    expect(ids(list)).toEqual(['e1', 'e2', 'w', 'e3', 'n1']);  // w stays third; the run restarts after it
    const lead = [wide, mk('e1', 'ESPN'), mk('e2', 'ESPN'), mk('e3', 'ESPN'), mk('n1', 'NFL.com')];
    expect(ids(lead)).toEqual(['w', 'e1', 'e2', 'n1', 'e3']);
  });

  it('does not change the input', () => {
    const list = [mk('e1', 'ESPN'), mk('e2', 'ESPN'), mk('e3', 'ESPN'), mk('n1', 'NFL.com')];
    const copy = [...list];
    mixSources(list);
    expect(list).toEqual(copy);
  });
});

describe('World News corner', () => {
  const now = new Date('2026-11-16T12:00:00Z');
  const mk = (id: string, topic: string, subtopic?: string, published = '2026-11-16T10:00:00Z') => ({ item: { id, title: id, url: 'https://x.test', summary: '', published, source: 's', topic: topic as 'world', subtopic }, cluster: undefined, sources: 1 });

  it('treats an untagged world story as the world sub-topic, and leaves a tagged or other story alone', () => {
    expect(subtopicOf(mk('a', 'world').item)).toBe('world');
    expect(subtopicOf(mk('b', 'tech', 'gadgets').item)).toBe('gadgets');
    expect(subtopicOf(mk('c', 'us').item)).toBeUndefined();
    expect(subtopicLabel('world')).toBe('World News');
  });

  it('adds a World News tile with the newest world story and the count', () => {
    const list = [mk('w1', 'world', undefined, '2026-11-16T09:00:00Z'), mk('w2', 'world', undefined, '2026-11-16T11:00:00Z'), mk('g1', 'tech', 'gadgets', '2026-11-16T08:00:00Z'), mk('u1', 'us')];
    const corners = discovery(list, now).corners;
    const world = corners.find((c) => c.id === 'world');
    expect(world).toMatchObject({ label: 'World News', topic: 'world', total: 2 });
    expect(world?.lead.item.id).toBe('w2');
    expect(corners.some((c) => c.id === 'gadgets')).toBe(true);
    expect(subtopicRoute('world', 'world')).toBe('#/discovery/world');
  });
});

describe('story outlets', () => {
  it('lists the distinct sources of a clustered story, the lead first', () => {
    const feed: Feed = {
      generated: '2026-11-17T12:00:00+00:00',
      items: [
        item('a', { source: 'NPR', cluster: 'k', topic: 'us' }),
        item('b', { source: 'BBC', cluster: 'k', topic: 'us' }),
        item('c', { source: 'BBC', cluster: 'k', topic: 'us' }),
      ],
      clusters: [{ id: 'k', title: 't', topic: 'us', lead: 'b', published: '', sources: 2, items: ['a', 'b', 'c'] }],
    };
    expect(stories(feed, 'us')[0]?.outlets).toEqual(['BBC', 'NPR']);
  });

  it('lists only the members present in the tab, while the count stays cluster-wide', () => {
    const feed: Feed = {
      generated: '2026-11-17T12:00:00+00:00',
      items: [
        item('a', { source: 'NPR', cluster: 'k', topic: 'us' }),
        item('b', { source: 'BBC', cluster: 'k', topic: 'world' }),
      ],
      clusters: [{ id: 'k', title: 't', topic: 'us', lead: 'a', published: '', sources: 5, items: ['a', 'b', 'x', 'y', 'z'] }],
    };
    const story = stories(feed, 'us')[0];
    expect(story?.sources).toBe(5);
    expect(story?.outlets).toEqual(['NPR']);
  });
});
