import { describe, expect, it } from 'vitest';

import { cleanMuted, keepItems, MAX_MUTED, MAX_MUTED_CHARS, mutedTest, withMutedWord, withoutMuted } from './mute';
import { DEFAULTS, loadSettings, parseSettings, SETTINGS_KEY, saveSettings, withoutSources } from './settings';
import type { Feed, Item } from './types';

const it_ = (id: string, title: string, over: Partial<Item> = {}): Item => ({ id, title, url: 'https://e.com', summary: '', published: 'p', source: 'AP', topic: 'us', ...over });

describe('withMutedWord', () => {
  it('cleans the text up and adds it', () => {
    expect(withMutedWord([], '  Super   Bowl ')).toEqual(['Super Bowl']);
    expect(withMutedWord(['a b'], 'Trump')).toEqual(['a b', 'Trump']);
  });
  it('leaves the list alone for a word that is too short, too long, already there (any case) or when the list is full', () => {
    const list = ['Trump'];
    expect(withMutedWord(list, 'x')).toBe(list);
    expect(withMutedWord(list, '   ')).toBe(list);
    expect(withMutedWord(list, 'x'.repeat(MAX_MUTED_CHARS + 1))).toBe(list);
    expect(withMutedWord(list, 'TRUMP')).toBe(list);
    const full = Array.from({ length: MAX_MUTED }, (_, n) => `word${n}`);
    expect(withMutedWord(full, 'another')).toBe(full);
  });
});

describe('cleanMuted', () => {
  it('keeps the usable words, once each, in their first spelling', () => {
    expect(cleanMuted(['Trump', 'trump', ' ', 'x', 'Super  Bowl', 'super bowl'])).toEqual(['Trump', 'Super Bowl']);
    expect(cleanMuted(Array.from({ length: MAX_MUTED + 5 }, (_, n) => `word${n}`))).toHaveLength(MAX_MUTED);
  });
});

describe('mutedTest', () => {
  it('matches a whole word or phrase in any case, not part of a longer word', () => {
    const hit = mutedTest(['Trump', 'super bowl']);
    expect(hit('TRUMP signs the bill')).toBe(true);
    expect(hit("Trump's tariffs")).toBe(true);
    expect(hit('Who won the Super   Bowl')).toBe(true);  // any run of white space inside a phrase
    expect(hit('A trumpet solo')).toBe(false);
    expect(hit('Trumpeters')).toBe(false);
    expect(hit('Pre-Trump era')).toBe(true);  // a hyphen is not a letter
    expect(hit('Nothing here')).toBe(false);
  });
  it('counts a plural or possessive of the word', () => {
    const hit = mutedTest(['tariff']);
    expect(hit('New tariffs hit imports')).toBe(true);
    expect(hit("The tariff's effect")).toBe(true);
    expect(hit('Tariffing again')).toBe(false);
  });
  it('treats punctuation in a word literally and finds nothing with no words', () => {
    expect(mutedTest(['C++', 'a.b'])('learning C++ today')).toBe(true);
    expect(mutedTest(['a.b'])('axb')).toBe(false);
    expect(mutedTest([])('anything')).toBe(false);
  });
  it('matches words with accents and other scripts', () => {
    expect(mutedTest(['café'])('The café reopens')).toBe(true);
    expect(mutedTest(['café'])('Cafés reopen')).toBe(true);  // a plural counts
    expect(mutedTest(['café'])('Cafétéria reopens')).toBe(false);  // a longer word does not
  });
});

describe('withoutMuted', () => {
  const feed: Feed = {
    generated: 'g',
    items: [
      it_('a', 'Trump signs the bill', { cluster: 'c1', source: 'AP' }),
      it_('b', 'President signs the bill', { cluster: 'c1', source: 'BBC' }),
      it_('c', 'Rain on Friday', { cluster: 'c2', source: 'AP' }),
      it_('d', 'Rain on Friday', { cluster: 'c2', source: 'BBC', summary: 'Trump is not mentioned in the title' }),
      it_('e', 'Markets rise'),
    ],
    clusters: [
      { id: 'c1', title: 'Trump signs the bill', topic: 'us', lead: 'a', published: '', sources: 2, items: ['a', 'b'] },
      { id: 'c2', title: 'Rain on Friday', topic: 'us', lead: 'c', published: '', sources: 2, items: ['c', 'd'] },
    ],
  };
  it('returns the same feed when nothing is muted', () => {
    expect(withoutMuted(feed, [])).toBe(feed);
  });
  it('drops a story whose headline or summary has the word, and the whole cluster when the cluster headline has it', () => {
    const out = withoutMuted(feed, ['trump']);
    expect(out.items.map((i) => i.id)).toEqual(['c', 'e']);  // a, b: cluster c1 is about the muted word; d: its summary has it
    expect(out.clusters.map((c) => [c.id, c.sources])).toEqual([['c2', 1]]);  // c2 keeps the one outlet left
  });
  it('drops a cluster when none of its stories is left, and leaves the rest of the feed as it was', () => {
    const out = withoutMuted(feed, ['Rain', 'Trump']);
    expect(out.items.map((i) => i.id)).toEqual(['e']);
    expect(out.clusters).toEqual([]);
    expect(out.generated).toBe('g');
  });
  it('does not match a phrase across the headline and the summary', () => {
    const f: Feed = { generated: 'g', items: [it_('x', 'Georgia wins the Bowl', { summary: 'Game ends in overtime' }), it_('y', 'A Bowl Game tonight')], clusters: [] };
    expect(withoutMuted(f, ['Bowl Game']).items.map((i) => i.id)).toEqual(['x']);
  });
  it('works together with hidden sources', () => {
    const out = withoutMuted(withoutSources(feed, ['BBC']), ['Markets']);
    expect(out.items.map((i) => i.id)).toEqual(['a', 'c']);
    expect(out.clusters.map((c) => [c.id, c.sources])).toEqual([['c1', 1], ['c2', 1]]);
  });
});

describe('keepItems', () => {
  it('counts the distinct sources still present in a cluster', () => {
    const f: Feed = { generated: 'g', items: [], clusters: [{ id: 'c', title: 't', topic: 'us', lead: 'a', published: '', sources: 3, items: ['a', 'b', 'c'] }] };
    const kept = keepItems(f, [it_('a', 'x', { cluster: 'c', source: 'AP' }), it_('b', 'y', { cluster: 'c', source: 'AP' })]);
    expect(kept.clusters[0]?.sources).toBe(1);
  });
});

describe('muted words in settings', () => {
  it('defaults to none', () => {
    expect(DEFAULTS.mutedWords).toEqual([]);
    expect(parseSettings(null).mutedWords).toEqual([]);
  });
  it('reads back what was stored, cleaned up, and drops anything else', () => {
    expect(parseSettings(JSON.stringify({ mutedWords: ['Trump', 'trump', ' Super  Bowl ', 7, '', 'x'] })).mutedWords).toEqual(['Trump', 'Super Bowl']);
    expect(parseSettings(JSON.stringify({ mutedWords: 'Trump' })).mutedWords).toEqual([]);
    expect(parseSettings(JSON.stringify({ mutedWords: ['x'.repeat(101)] })).mutedWords).toEqual([]);
  });
  it('round-trips through the stored settings', () => {
    const store = new Map<string, string>();
    const ls = { getItem: (k: string) => store.get(k) ?? null, setItem: (k: string, v: string) => { store.set(k, v); } };
    Object.defineProperty(globalThis, 'localStorage', { value: ls, configurable: true });
    saveSettings({ ...DEFAULTS, mutedWords: ['Trump', 'Super Bowl'] });
    expect(store.has(SETTINGS_KEY)).toBe(true);
    expect(loadSettings().mutedWords).toEqual(['Trump', 'Super Bowl']);
    Reflect.deleteProperty(globalThis, 'localStorage');
  });
});
