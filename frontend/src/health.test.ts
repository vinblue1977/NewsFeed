import { describe, expect, it } from 'vitest';

import { needAttention, sourceHealth } from './health';

describe('sourceHealth', () => {
  const sources = {
    npr: { name: 'NPR', ok: true, items: 10 },
    'abc-politics': { name: 'ABC News', ok: true, items: 1 },
    reason: { name: 'Reason', ok: true, items: 0, filtered: 12 },
    bad: { name: 'Broken', ok: false, items: 0, error: 'HTTP Error 404: Not Found' },
    'local-0': { ok: true, items: 3 },
    'local-1': { ok: true, items: 0 },
    dup: { name: 'Direct', ok: true, items: 0, duplicates: 4 },
  };
  it('puts failed first, then empty, then the rest by name', () => {
    expect(sourceHealth(sources).map((r) => r.id)).toEqual(['bad', 'local-1', 'reason', 'abc-politics', 'dup', 'local-0', 'npr']);
  });
  it('says what happened to each feed', () => {
    const by = Object.fromEntries(sourceHealth(sources).map((r) => [r.id, r]));
    expect(by.bad).toMatchObject({ state: 'failed', note: 'failed: HTTP Error 404: Not Found' });
    expect(by.reason).toMatchObject({ state: 'empty', note: '0 stories (12 filtered)' });
    expect(by['abc-politics']).toMatchObject({ state: 'ok', note: '1 story' });
    expect(by.npr?.note).toBe('10 stories');
    expect(by.dup).toMatchObject({ state: 'ok', note: '0 new (4 stories already from another feed)' });  // fetched fine: not a problem
  });
  it('shows a local feed with no name as "Local feed N", and one that has a name by it', () => {
    const labels = sourceHealth(sources).filter((r) => r.id.startsWith('local-')).map((r) => r.label).sort();
    expect(labels).toEqual(['Local feed 1', 'Local feed 2']);
    expect(sourceHealth({ 'local-official-0': { name: 'village.example', ok: true, items: 4 } })[0]?.label).toBe('village.example');
  });
  it('numbers a local feed from its id, so the label does not move and 2 sorts before 10', () => {
    const rows = sourceHealth({ 'local-9': { ok: true, items: 1 }, 'local-1': { ok: true, items: 1 }, 'local-official-0': { ok: true, items: 1 }, 'local-alert-0': { ok: true, items: 1 } });
    expect(rows.map((r) => r.label)).toEqual(['Local alert feed 1', 'Local feed 2', 'Local feed 10', 'Local official feed 1']);
  });
  it('shows the id, not a local label, for an old feed.json entry with no name', () => {
    expect(sourceHealth({ npr: { ok: true, items: 4 } })[0]?.label).toBe('npr');
  });
  it('counts the feeds that need a look, and copes with no data', () => {
    expect(needAttention(sourceHealth(sources))).toBe(3);  // bad, local-1 and reason; the duplicate-only feed is fine
    expect(sourceHealth(undefined)).toEqual([]);
    expect(needAttention([])).toBe(0);
  });
  it('cuts a very long error and handles a failure with no message', () => {
    const rows = sourceHealth({ a: { name: 'A', ok: false, items: 0, error: 'x'.repeat(200) }, b: { name: 'B', ok: false, items: 0 } });
    expect(rows.find((r) => r.id === 'a')?.note.length).toBe('failed: '.length + 60);
    expect(rows.find((r) => r.id === 'b')?.note).toBe('failed');
  });
});
