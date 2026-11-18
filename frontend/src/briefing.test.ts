import { describe, expect, it } from 'vitest';

import { dayKey, loadRead, markRead, type KeyValue } from './briefing';

function memory(): KeyValue & { data: Map<string, string> } {
  const data = new Map<string, string>();
  return { data, getItem: (k) => data.get(k) ?? null, setItem: (k, v) => void data.set(k, v) };
}

describe('briefing progress', () => {
  it('formats the local day', () => {
    expect(dayKey(new Date(2026, 10, 7, 23, 59))).toBe('2026-11-07');
  });
  it('remembers what was read today, once each', () => {
    const kv = memory();
    expect(markRead('2026-11-17', 'a', kv)).toEqual(['a']);
    expect(markRead('2026-11-17', 'b', kv)).toEqual(['a', 'b']);
    expect(markRead('2026-11-17', 'a', kv)).toEqual(['a', 'b']);
    expect(loadRead('2026-11-17', kv)).toEqual(['a', 'b']);
  });
  it('starts empty on a new day', () => {
    const kv = memory();
    markRead('2026-11-17', 'a', kv);
    expect(loadRead('2026-11-18', kv)).toEqual([]);
  });
  it('survives bad stored data and missing storage', () => {
    const kv = memory();
    kv.data.set('news.briefing', '{oops');
    expect(loadRead('d', kv)).toEqual([]);
    expect(loadRead('d', undefined)).toEqual([]);
    expect(markRead('d', 'a', undefined)).toEqual(['a']);
  });
  it('ignores a throwing store', () => {
    const kv: KeyValue = { getItem: () => null, setItem: () => { throw new Error('quota'); } };
    expect(markRead('d', 'a', kv)).toEqual(['a']);
  });
});
