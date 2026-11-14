import { describe, expect, it } from 'vitest';

import { DEFAULTS, parseSettings, readSize, sourceNames, toggled, withoutSources } from './settings';
import type { Feed } from './types';

const it_ = (id: string, source: string, cluster?: string) => ({ id, title: id, url: 'https://e.com', summary: '', published: 'p', source, topic: 'us' as const, cluster });
const feed: Feed = {
  generated: 'g',
  items: [it_('a', 'AP', 'c1'), it_('b', 'BBC', 'c1'), it_('c', 'AP', 'c2'), it_('d', 'CNN')],
  clusters: [
    { id: 'c1', title: 't', topic: 'us', lead: 'a', published: '', sources: 2, items: ['a', 'b'] },
    { id: 'c2', title: 't', topic: 'us', lead: 'c', published: '', sources: 1, items: ['c'] },
  ],
};

describe('settings', () => {
  it('falls back to defaults for anything unreadable', () => {
    expect(parseSettings(null)).toEqual(DEFAULTS);
    expect(parseSettings('not json')).toEqual(DEFAULTS);
    expect(parseSettings('5')).toEqual(DEFAULTS);
    expect(parseSettings('null')).toEqual(DEFAULTS);
  });
  it('keeps valid values and drops bad ones', () => {
    const s = parseSettings(JSON.stringify({ textSize: 'large', hiddenSources: ['AP', 'AP', 3, '', 'x'.repeat(101)], hiddenTickers: 'no' }));
    expect(s).toEqual({ textSize: 'large', hiddenSources: ['AP'], hiddenTickers: [] });
    expect(parseSettings(JSON.stringify({ textSize: 'huge' })).textSize).toBe('medium');
  });
  it('caps list length', () => {
    const many = Array.from({ length: 500 }, (_, n) => `s${n}`);
    expect(parseSettings(JSON.stringify({ hiddenSources: many })).hiddenSources).toHaveLength(200);
  });
  it('maps sizes and toggles names', () => {
    expect(readSize('small')).toBe(16);
    expect(readSize('large')).toBe(21);
    expect(toggled(['a'], 'b')).toEqual(['a', 'b']);
    expect(toggled(['a', 'b'], 'a')).toEqual(['b']);
  });
  it('hides sources and recounts clusters', () => {
    expect(withoutSources(feed, [])).toBe(feed);
    const out = withoutSources(feed, ['AP']);
    expect(out.items.map((i) => i.id)).toEqual(['b', 'd']);
    expect(out.clusters).toEqual([{ ...feed.clusters[0], sources: 1 }]);
  });
  it('lists sources, including hidden ones that left the feed', () => {
    expect(sourceNames(feed, ['Zed'])).toEqual(['AP', 'BBC', 'CNN', 'Zed']);
    expect(sourceNames(undefined, [])).toEqual([]);
  });
});
