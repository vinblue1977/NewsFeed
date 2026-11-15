import { describe, expect, it } from 'vitest';

import { TOPICS, badgeColor, briefing, imageSrc, sections, coverage, initial, parseFeed, parseRoute, readerPage, storyLink, storyPage, isStale, safeUrl, splitRecent, discovery, subtopicLabel, stories, timeAgo, topicLabel, topStory } from './feed';
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

  it('lists coverage from other sources only', () => {
    const lead = stories(feed, 'us')[0];
    if (!lead) throw new Error('no lead');
    expect(coverage(feed, lead).map((i) => i.id)).toEqual(['b']);
    expect(coverage(feed, { item: item('q'), cluster: undefined, sources: 1 })).toEqual([]);
  });

  it('builds a briefing: lead story, then a few recent stories per topic group, no repeats', () => {
    const b = briefing(feed, NOW);
    expect(b.top?.item.id).toBe('a');
    expect(b.groups.map((g) => g.label)).toEqual(['World · India']);
    expect(b.groups[0]?.stories.map((s) => s.item.id)).toEqual(['d']);
    expect(b.total).toBe(2);  // 'e' is days old, so left out
    const many: Feed = {
      ...feed,
      clusters: [],
      items: Array.from({ length: 6 }, (_, n) => item(`t${n}`, { topic: 'tech', published: `2026-11-13T11:0${n}:00+00:00` })),
    };
    expect(briefing(many, NOW).groups[0]?.stories).toHaveLength(3);
    expect(briefing({ ...feed, items: [], clusters: [] }, NOW)).toEqual({ top: undefined, groups: [], total: 0 });
  });

  it('keeps stories from topics it has no group for, in a "More" group', () => {
    const odd: Feed = {
      ...feed,
      clusters: [],
      items: [item('s1', { topic: 'us', published: '2026-11-13T11:30:00+00:00' }), item('s2', { topic: 'science' as never })],
    };
    const b = briefing(odd, NOW);
    expect(b.top?.item.id).toBe('s1');
    expect(b.groups.map((g) => [g.label, g.stories.map((s) => s.item.id)])).toEqual([['More', ['s2']]]);
    expect(b.total).toBe(2);
  });

  it('ignores unparseable dates, treats future dates as now, and cuts off at 24 hours', () => {
    const dated: Feed = {
      ...feed,
      clusters: [],
      items: [
        item('bad', { published: 'sometime yesterday' }),
        item('future', { published: '2026-11-14T09:00:00+00:00' }),
        item('edge', { published: '2026-11-12T12:00:01+00:00' }),
        item('old', { published: '2026-11-12T11:59:59+00:00' }),
      ],
    };
    const b = briefing(dated, NOW);
    const ids = [b.top?.item.id, ...b.groups.flatMap((g) => g.stories.map((s) => s.item.id))].sort();
    expect(ids).toEqual(['edge', 'future']);
  });

  it('does not repeat the lead story\'s cluster further down', () => {
    const b = briefing(feed, NOW);
    const shown = [b.top, ...b.groups.flatMap((g) => g.stories)].map((s) => s?.cluster?.id).filter(Boolean);
    expect(new Set(shown).size).toBe(shown.length);
  });

  it('reads the route from the URL hash', () => {
    expect(parseRoute('#/local')).toEqual({ kind: 'local' });
    expect(parseRoute('#/discovery')).toEqual({ kind: 'discovery' });
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
      story('top', 'sports'), story('s1', 'sports'),
    ];
    const out = sections(list, list[5]);
    expect(out.map((s) => s.topic)).toEqual(['us', 'world', 'sports']);
    const us = out[0];
    expect(us?.lead.item.id).toBe('u2');  // the one with a picture
    expect(us?.more.map((s) => s.item.id)).toEqual(['u1', 'u3']);  // then the newest others, two at most
    expect(us?.total).toBe(4);
    expect(out[2]?.lead.item.id).toBe('s1');
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

describe('local stories stay out of For You', () => {
  const now = new Date('2026-11-15T12:00:00Z');
  const item = (id: string, topic: 'us' | 'local', cluster?: string) => ({ id, title: id, url: 'https://x.test', summary: '', published: '2026-11-15T10:00:00Z', source: 's', topic, cluster });
  const feed = {
    generated: '2026-11-15T11:30:00Z',
    items: [item('a', 'us'), item('l1', 'local'), item('l2', 'local', 'c1'), item('l3', 'local', 'c1')],
    clusters: [{ id: 'c1', title: 'Local cluster', topic: 'local' as const, lead: 'l2', published: '2026-11-15T10:00:00Z', sources: 2, items: ['l2', 'l3'] }],
  };
  it('leaves local out of "all" but still returns it for the local topic', () => {
    expect(stories(feed, 'all').map((s) => s.item.id)).toEqual(['a']);
    expect(stories(feed, 'local').map((s) => s.item.id).sort()).toEqual(['l1', 'l2']);
  });
  it('keeps a local cluster out of For You even when a non-local story joined it', () => {
    const mixed = { ...feed, items: [...feed.items, item('u', 'us', 'c1')] };
    expect(stories(mixed, 'all').map((s) => s.item.id)).toEqual(['a']);
  });
  it('has no Local topic chip, section or briefing group, and still labels local stories', () => {
    expect(TOPICS.map((t) => t.id)).not.toContain('local');
    expect(topicLabel('local')).toBe('Local');
    expect(briefing(feed, now).groups.map((g) => g.label)).not.toContain('Local');
    expect(sections(stories(feed, 'all'), undefined).map((s) => s.topic)).not.toContain('local');
    expect(briefing(feed, now).total).toBe(1);
  });
});
