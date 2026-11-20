import { describe, expect, it } from 'vitest';

import { activePreMarket, etClock, parseMarkets, preMarketLabel, signedPercent } from './markets';

const read = {
  state: 'lean_up',
  futures: [{ symbol: 'ES=F', name: 'S&P', change_pct: 0.3 }, { symbol: 'NQ=F', name: 'Nasdaq', change_pct: 0.4 }, { symbol: 'YM=F', name: 'Dow', change_pct: 0.1 }],
  vix: { price: 19.6, change_pct: 6.2, vote: -1 },
  yield10: { price: 4.38, change_bp: 5, vote: -1 },
};
const doc = (premarket: unknown, generated = '2026-11-17T13:10:00+00:00') => parseMarkets({ generated, indexes: [], tickers: [], premarket });

describe('pre-market read', () => {
  it('is parsed from the document', () => {
    expect(doc(read)?.premarket).toEqual({
      state: 'lean_up',
      futures: [{ symbol: 'ES=F', name: 'S&P', changePct: 0.3 }, { symbol: 'NQ=F', name: 'Nasdaq', changePct: 0.4 }, { symbol: 'YM=F', name: 'Dow', changePct: 0.1 }],
      vix: { price: 19.6, changePct: 6.2, vote: -1 },
      yield10: { price: 4.38, changeBp: 5, vote: -1 },
    });
  });

  it('is absent when missing, null or malformed, and never breaks the document', () => {
    for (const bad of [undefined, null, 'x', { ...read, state: 'moon' }, { ...read, futures: [read.futures[0]] }, { ...read, futures: 'x' }]) {
      const m = doc(bad);
      expect(m).toBeDefined();
      expect(m?.premarket).toBeUndefined();
    }
  });

  it('keeps a read without the VIX or the yield, and ignores junk votes and numbers', () => {
    const m = doc({ ...read, vix: null, yield10: { price: 4.1, change_bp: 'x', vote: 1 } });
    expect(m?.premarket?.vix).toBeNull();
    expect(m?.premarket?.yield10).toBeNull();
    expect(doc({ ...read, vix: { price: 20, change_pct: 1, vote: 7 } })?.premarket?.vix?.vote).toBe(0);
  });

  it('drops a future without a usable move', () => {
    const m = doc({ ...read, futures: [...read.futures, { symbol: 'X', name: 'Bad', change_pct: null }, null] });
    expect(m?.premarket?.futures.map((f) => f.symbol)).toEqual(['ES=F', 'NQ=F', 'YM=F']);
  });

  it('shows only while fresh and before the open', () => {
    const m = doc(read);
    expect(activePreMarket(m, new Date('2026-11-17T13:15:00+00:00'))?.state).toBe('lean_up');  // 8:15 AM Eastern, Tuesday
    expect(activePreMarket(m, new Date('2026-11-17T13:31:00+00:00'))).toBeUndefined();  // the file is 21 minutes old
    expect(activePreMarket(m, new Date('2026-11-17T14:31:00+00:00'))).toBeUndefined();  // after 9:30 AM Eastern
    expect(activePreMarket(doc(read, '2026-11-21T13:10:00+00:00'), new Date('2026-11-21T13:15:00+00:00'))).toBeUndefined();  // Saturday
    expect(activePreMarket(doc(undefined), new Date('2026-11-17T13:15:00+00:00'))).toBeUndefined();
    expect(activePreMarket(undefined, new Date())).toBeUndefined();
  });

  it('still shows when a watchlist symbol trades around the clock (crypto, an Indian stock)', () => {
    const m = parseMarkets({
      generated: '2026-11-17T13:10:00+00:00', indexes: [], premarket: read,
      tickers: [{ symbol: 'BTC-USD', ok: true, price: 1, name: 'Bitcoin', currency: 'USD', open: true }],
    });
    expect(m?.tickers[0]?.open).toBe(true);
    expect(activePreMarket(m, new Date('2026-11-17T13:15:00+00:00'))?.state).toBe('lean_up');
  });

  it('labels each state with an arrow as well as a colour', () => {
    expect(preMarketLabel('bull')).toEqual({ text: 'Bullish', arrow: '▲', dir: 'up' });
    expect(preMarketLabel('lean_down')).toEqual({ text: 'Leaning down', arrow: '↘', dir: 'down' });
    expect(preMarketLabel('flat').dir).toBe('flat');
  });

  it('formats signed percents, with a move that rounds to nothing shown as flat', () => {
    expect(signedPercent(0.64)).toEqual({ text: '+0.6%', dir: 'up' });
    expect(signedPercent(-0.84)).toEqual({ text: '−0.8%', dir: 'down' });
    expect(signedPercent(0.04)).toEqual({ text: '0.0%', dir: 'flat' });
    expect(signedPercent(-0.004, 2)).toEqual({ text: '0.00%', dir: 'flat' });
  });

  it('writes the time in Eastern time', () => {
    expect(etClock('2026-11-17T13:42:00+00:00')).toBe('8:42 AM ET');
    expect(etClock('2026-07-17T12:42:00+00:00')).toBe('8:42 AM ET');  // summer time
    expect(etClock('garbage')).toBe('');
  });
});
