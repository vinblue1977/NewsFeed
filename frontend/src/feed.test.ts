import { describe, expect, it } from 'vitest';

import { badgeColor, briefing, coverage, initial, parseFeed, parseRoute, readerPage, storyLink, storyPage, isStale, safeUrl, stories, timeAgo, topicLabel, topStory } from './feed';
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
    expect(parseRoute('#/markets')).toEqual({ kind: 'markets' });
    expect(parseRoute('#/settings')).toEqual({ kind: 'settings' });
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
