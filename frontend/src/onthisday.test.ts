import { describe, expect, it } from 'vitest';
import { factFor, parseOnThisDay } from './onthisday';

const good = { year: 1985, text: 'Windows 1.0 was released.' };
const doc = (days: unknown) => ({ generated: 'g', date: '2026-11-20', days });

describe('parseOnThisDay', () => {
  it('reads the days and trims the text', () => {
    expect(parseOnThisDay(doc({ '2026-11-20': good, '2026-11-21': { year: 1947, text: '  Padded.  ' } }))).toEqual({
      days: { '2026-11-20': good, '2026-11-21': { year: 1947, text: 'Padded.' } },
    });
  });

  it('keeps the good days and drops a malformed one', () => {
    const days = {
      '2026-11-19': { ...good, year: 0 }, '2026-11-20': good, 'today': good, '2026-11-21': { ...good, text: '' },
      '2026-11-22': { ...good, text: 'x'.repeat(201) }, '2026-11-23': { ...good, year: '1985' }, '2026-11-24': null, '2026-11-25': 5,
    };
    expect(Object.keys(parseOnThisDay(doc(days))?.days ?? {})).toEqual(['2026-11-20']);
  });

  it('gives undefined for anything that is not a document, or has no usable day', () => {
    for (const v of [null, 'x', 5, {}, [], { days: null }, { days: [] }, { days: 'x' }, doc({}), doc({ '2026-11-20': { year: 0, text: 'x' } })]) {
      expect(parseOnThisDay(v)).toBeUndefined();
    }
  });
});

describe('factFor', () => {
  const parsed = parseOnThisDay(doc({ '2026-11-20': good }));
  it('finds the reader\'s own day, and nothing for another one, a missing document or an inherited name', () => {
    expect(factFor(parsed, '2026-11-20')).toEqual(good);
    expect(factFor(parsed, '2026-11-21')).toBeUndefined();
    expect(factFor(undefined, '2026-11-20')).toBeUndefined();
    expect(factFor(parsed, 'constructor')).toBeUndefined();
  });
});
