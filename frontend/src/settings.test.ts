import { describe, expect, it } from 'vitest';

import { DEFAULTS, parseSettings, withTeam, readSize, shownCount, sourceNames, toggled, withoutSources } from './settings';
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
    expect(s).toEqual({ textSize: 'large', hiddenSources: ['AP'], hiddenTickers: [], watchCollapsed: false, earningsCollapsed: false, cornersCollapsed: false, scheduleCollapsed: false, scoresCollapsed: [], following: [], teamColors: true, myTeams: [], watchKey: '', push: DEFAULTS.push });
    expect(parseSettings(JSON.stringify({ push: { topics: ['us', 'x'], weather: false, quietStart: '23:00' } })).push)
      .toEqual({ topics: ['us'], weather: false, alerts: true, quietStart: '23:00', quietEnd: '07:00' });  // an old save has no alerts field: on
    expect(parseSettings(JSON.stringify({ push: 'junk' })).push).toEqual(DEFAULTS.push);
    expect(parseSettings(JSON.stringify({ watchCollapsed: true })).watchCollapsed).toBe(true);
    expect(parseSettings(JSON.stringify({ watchCollapsed: 'yes' })).watchCollapsed).toBe(false);
    expect(parseSettings(JSON.stringify({ earningsCollapsed: true })).earningsCollapsed).toBe(true);
    expect(parseSettings(JSON.stringify({ earningsCollapsed: 1 })).earningsCollapsed).toBe(false);
    expect(parseSettings(JSON.stringify({ cornersCollapsed: true })).cornersCollapsed).toBe(true);
    expect(parseSettings(JSON.stringify({ cornersCollapsed: 1 })).cornersCollapsed).toBe(false);
    expect(parseSettings(JSON.stringify({ scheduleCollapsed: true })).scheduleCollapsed).toBe(true);
    expect(parseSettings(JSON.stringify({ scheduleCollapsed: 'yes' })).scheduleCollapsed).toBe(false);
    expect(parseSettings(JSON.stringify({ scoresCollapsed: ['nfl', 'bogus', 5, 'nfl', 'cricket'] })).scoresCollapsed).toEqual(['nfl', 'cricket']);
    expect(parseSettings(JSON.stringify({ scoresCollapsed: 'nfl' })).scoresCollapsed).toEqual([]);
    expect(parseSettings(JSON.stringify({ watchKey: 'a1b2c3d4e5f6a7b8' })).watchKey).toBe('a1b2c3d4e5f6a7b8');
    for (const bad of ['short', 'UPPERCASEUPPERCASE', '../data/feed', 5, '']) expect(parseSettings(JSON.stringify({ watchKey: bad })).watchKey).toBe('');
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

describe('shownCount', () => {
  it('ignores hidden entries that are no longer listed', () => {
    expect(shownCount(['A', 'B', 'C'], ['B', 'GONE'])).toBe(2);
    expect(shownCount([], ['B'])).toBe(0);
  });
});

describe('my teams settings', () => {
  it('keeps clean, short, unique names and a bounded list', () => {
    expect(parseSettings(JSON.stringify({ myTeams: ['Bears', 'Bears', '', 5, 'x'.repeat(41)] })).myTeams).toEqual(['Bears']);
    expect(parseSettings(JSON.stringify({ myTeams: 'Bears' })).myTeams).toEqual([]);
    expect(parseSettings(JSON.stringify({ myTeams: ['Bears', 'bears', ' New   York '] })).myTeams).toEqual(['Bears', 'New York']);
  });
  it('adds a name once, ignoring case and spacing, and stops at the limit', () => {
    expect(withTeam([], '  New   York  Giants ')).toEqual(['New York Giants']);
    expect(withTeam(['Bears'], 'bears')).toEqual(['Bears']);
    expect(withTeam(['Bears'], '  ')).toEqual(['Bears']);
    expect(withTeam(['Bears'], 'x'.repeat(41))).toEqual(['Bears']);
    const full = Array.from({ length: 20 }, (_, i) => `T${i}`);
    expect(withTeam(full, 'More')).toEqual(full);
  });

  it('keeps only readable follows, once each', () => {
    expect(parseSettings(JSON.stringify({ following: ['topic:gadgets', 'topic:gadgets', 'kw:US election,midterms', 'kw:', 'topic:', 'junk', 5] })).following).toEqual(['topic:gadgets', 'kw:US election,midterms']);
    expect(parseSettings(JSON.stringify({ following: 'topic:gadgets' })).following).toEqual([]);
  });

  it('has team colours on unless it is switched off', () => {
    expect(parseSettings(null).teamColors).toBe(true);
    expect(parseSettings(JSON.stringify({})).teamColors).toBe(true);
    expect(parseSettings(JSON.stringify({ teamColors: false })).teamColors).toBe(false);
    expect(parseSettings(JSON.stringify({ teamColors: 'no' })).teamColors).toBe(true);  // only a real false turns it off
  });
});
