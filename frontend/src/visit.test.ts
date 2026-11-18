import { describe, expect, it } from 'vitest';

import type { KeyValue } from './briefing';
import type { Story } from './feed';
import type { Item } from './types';
import { countNew, dividerAt, dividerLabel, loadLastVisit, MAX_GAP_MS, MIN_GAP_MS, saveVisit, sinceWhen } from './visit';

const story = (id: string, published: string): Story => ({
  item: { id, title: id, url: `https://x/${id}`, summary: '', published, source: 's', topic: 'us' } as Item,
  cluster: undefined,
  sources: 1,
});
const SINCE = Date.UTC(2026, 10, 17, 12, 0);
const at = (min: number) => new Date(SINCE + min * 60_000).toISOString();

function memory(): KeyValue & { data: Map<string, string> } {
  const data = new Map<string, string>();
  return { data, getItem: (k) => data.get(k) ?? null, setItem: (k, v) => void data.set(k, v) };
}

describe('last visit', () => {
  it('round-trips the time and ignores junk', () => {
    const kv = memory();
    expect(loadLastVisit(kv)).toBeUndefined();
    saveVisit(SINCE, kv);
    expect(loadLastVisit(kv)).toBe(SINCE);
    kv.data.set('news.lastVisit', 'soon');
    expect(loadLastVisit(kv)).toBeUndefined();
    expect(loadLastVisit(undefined)).toBeUndefined();
  });
  it('survives a throwing store', () => {
    const kv: KeyValue = { getItem: () => { throw new Error('blocked'); }, setItem: () => { throw new Error('quota'); } };
    expect(loadLastVisit(kv)).toBeUndefined();
    expect(() => { saveVisit(1, kv); }).not.toThrow();
  });
});

describe('sinceWhen', () => {
  it('needs a gap between ten minutes and a day', () => {
    expect(sinceWhen(undefined, SINCE)).toBeUndefined();
    expect(sinceWhen(SINCE, SINCE + MIN_GAP_MS - 1)).toBeUndefined();
    expect(sinceWhen(SINCE, SINCE + MIN_GAP_MS)).toBe(SINCE);
    expect(sinceWhen(SINCE, SINCE + MAX_GAP_MS)).toBe(SINCE);
    expect(sinceWhen(SINCE, SINCE + MAX_GAP_MS + 1)).toBeUndefined();
  });
});

describe('divider', () => {
  const list = [story('a', at(30)), story('b', at(10)), story('c', at(-5)), story('d', at(-60))];
  it('counts new and seen stories', () => {
    expect(countNew(list, SINCE)).toEqual({ fresh: 2, seen: 2 });
    expect(countNew([story('x', 'nonsense')], SINCE)).toEqual({ fresh: 0, seen: 1 });
  });
  it('goes before the first story that is not new', () => {
    expect(dividerAt(list, SINCE)).toBe(2);
  });
  it('is absent when nothing is new or nothing older is shown', () => {
    expect(dividerAt([story('c', at(-5))], SINCE)).toBe(-1);
    expect(dividerAt([story('a', at(30)), story('b', at(10))], SINCE)).toBe(-1);
    expect(dividerAt([], SINCE)).toBe(-1);
  });
  it('words the label', () => {
    expect(dividerLabel(3, SINCE, 'en-US')).toMatch(/^3 new since you last looked · \d{1,2}:\d{2}\s?[AP]M$/);
    expect(dividerLabel(2, SINCE, 'en-US', true)).toMatch(/^2 new · \d{1,2}:\d{2}\s?[AP]M$/);
  });
});
