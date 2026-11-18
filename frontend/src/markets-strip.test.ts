import { describe, expect, it } from 'vitest';

import { earningsToday, marketPhase, stripMoves } from './markets';

const q = (symbol: string, pct: number | null, open = false) => ({
  symbol, name: symbol, price: 10, prevClose: null, dayOpen: null, dayHigh: null, dayLow: null, history: [],
  change: pct === null ? null : pct / 10, changePct: pct, currency: 'USD', open, lastTrade: null, series: [],
});
const doc = (tickers: ReturnType<typeof q>[], generated = '2026-11-17T14:00:00+00:00') => ({ generated, indexes: [], tickers, missing: 0 });

describe('home markets strip', () => {
  it('lists the biggest movers first, at most four, and counts the rest', () => {
    const { moves, more } = stripMoves([q('B', 0.5), q('A', -1.2), q('C', 1.9), q('D', 0.1), q('E', -0.1), q('F', null)]);
    expect(moves.map((m) => m.symbol)).toEqual(['C', 'A', 'B', 'D']);
    expect(moves.map((m) => m.text)).toEqual(['+1.9%', '−1.2%', '+0.5%', '+0.1%']);
    expect(moves.map((m) => m.dir)).toEqual(['up', 'down', 'up', 'up']);
    expect(more).toBe(1);
  });

  it('handles an empty list and shows a move that rounds to zero as flat', () => {
    expect(stripMoves([])).toEqual({ moves: [], more: 0 });
    expect(stripMoves([q('A', 0.04), q('B', -0.04)]).moves).toEqual([
      { symbol: 'A', text: '0.0%', dir: 'flat' },
      { symbol: 'B', text: '0.0%', dir: 'flat' },
    ]);
  });

  it('is open when a fresh document says so', () => {
    const now = new Date('2026-11-17T15:00:00+00:00');  // 10:00 AM Eastern, a Tuesday
    expect(marketPhase(doc([q('A', 1, true)], '2026-11-17T14:58:00+00:00'), now)).toBe('open');
  });

  it('is pre-open on a weekday before 9:30 Eastern, closed after, and closed at the weekend', () => {
    const closed = doc([q('A', 1)], '2026-11-17T13:00:00+00:00');
    expect(marketPhase(closed, new Date('2026-11-17T13:12:00+00:00'))).toBe('pre-open');  // 8:12 AM EST
    expect(marketPhase(closed, new Date('2026-11-17T22:00:00+00:00'))).toBe('closed');  // 5:00 PM EST
    expect(marketPhase(closed, new Date('2026-11-21T13:12:00+00:00'))).toBe('closed');  // Saturday morning
  });

  it('is closed in the small hours, and a stock from another exchange does not make it open', () => {
    const closed = doc([q('A', 1)], '2026-11-17T06:00:00+00:00');
    expect(marketPhase(closed, new Date('2026-11-17T07:00:00+00:00'))).toBe('closed');  // 2:00 AM EST
    const abroad = { ...q('RELIANCE.NS', 1, true), currency: 'INR' };
    const mixed = doc([q('A', 1, false), abroad], '2026-11-17T13:00:00+00:00');
    expect(marketPhase(mixed, new Date('2026-11-17T13:12:00+00:00'))).toBe('pre-open');
  });

  it('is never open from a stale document', () => {
    expect(marketPhase(doc([q('A', 1, true)], '2026-11-17T01:00:00+00:00'), new Date('2026-11-17T15:00:00+00:00'))).toBe('closed');
  });

  it("words today's earnings", () => {
    const now = new Date(2026, 10, 17, 9);
    const earnings = {
      generated: 'g',
      items: [
        { symbol: 'AAA', date: '2026-11-17', time: 'post' as const, eps: null },
        { symbol: 'BBB', date: '2026-11-17', time: 'pre' as const, eps: null },
        { symbol: 'CCC', date: '2026-11-17', time: 'tbd' as const, eps: null },
        { symbol: 'DDD', date: '2026-11-18', time: 'post' as const, eps: null },
        { symbol: 'EEE', date: '2026-11-17', time: 'post' as const, eps: null },
      ],
    };
    expect(earningsToday(earnings, ['AAA', 'BBB', 'CCC', 'DDD'], now)).toEqual(['AAA after the close', 'BBB before the open', 'CCC']);
    expect(earningsToday(undefined, ['AAA'], now)).toEqual([]);
  });
});
