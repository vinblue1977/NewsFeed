import { describe, expect, it } from 'vitest';

import { badgeColor, coverage, initial, parseFeed, isStale, safeUrl, stories, timeAgo, topicLabel, topStory } from './feed';
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
});
