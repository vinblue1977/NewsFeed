import { describe, expect, it } from 'vitest';

import { formatChange, formatPrice, isFresh, parseMarkets, priceLabel, sparkline, formatMove, dayRange, historyChange, isMarketNews, watchTerms } from './markets';

const quote = (over: Record<string, unknown> = {}) => ({
  symbol: '^GSPC', name: 'S&P 500', ok: true, price: 7561.67, change: -30.73, change_pct: -0.4,
  currency: 'USD', open: false, last_trade: '2026-11-13T21:00:00+00:00', series: [1, 2, 3], ...over,
});

describe('parseMarkets', () => {
  it('keeps readable quotes and counts the ones the ingest could not read', () => {
    const m = parseMarkets({ generated: 'g', indexes: [quote(), { symbol: '^DJI', ok: false }], tickers: [quote({ symbol: 'AAPL' })] });
    expect(m?.indexes).toHaveLength(1);
    expect(m?.tickers[0]?.symbol).toBe('AAPL');
    expect(m?.missing).toBe(1);
    expect(parseMarkets({ generated: 'g', indexes: [quote(), null, { nosymbol: 1 }] })?.missing).toBe(2);
    expect(m?.indexes[0]).toMatchObject({ price: 7561.67, changePct: -0.4, open: false, lastTrade: '2026-11-13T21:00:00+00:00' });
  });
  it('tolerates a missing last_trade, bad series values and odd types', () => {
    const m = parseMarkets({ generated: 'g', indexes: [quote({ last_trade: undefined, series: [1, null, 'x', 2], name: 5, currency: 3 })] });
    expect(m?.indexes[0]).toMatchObject({ lastTrade: null, series: [1, 2], name: '^GSPC', currency: '' });
  });
  it('rejects documents without a stamp; an empty or unreadable list still counts, as missing quotes', () => {
    expect(parseMarkets(null)).toBeUndefined();
    expect(parseMarkets({ indexes: [quote()] })).toBeUndefined();
    expect(parseMarkets({ generated: 'g', indexes: [], tickers: [] })?.tickers).toEqual([]);  // an empty watchlist
    expect(parseMarkets({ generated: 'g', indexes: [{ symbol: 'x', ok: false }], tickers: 'nope' })?.missing).toBe(1);
    expect(parseMarkets({ generated: 'g', indexes: [null, 5, quote({ price: 'NaN' })] })?.missing).toBe(3);
  });
});

describe('isFresh', () => {
  const now = new Date('2026-11-14T12:00:00Z');
  it('is fresh for the last hour only', () => {
    expect(isFresh('2026-11-14T11:30:00Z', now)).toBe(true);
    expect(isFresh('2026-11-14T10:30:00Z', now)).toBe(false);
    expect(isFresh('2026-11-14T13:00:00Z', now)).toBe(false);
    expect(isFresh('nonsense', now)).toBe(false);
  });
});

describe('formatting', () => {
  it('formats prices and changes with a direction', () => {
    expect(formatPrice(25136.2)).toBe('25,136.20');
    expect(formatChange(-30.73, -0.4)).toEqual({ text: '▼ 0.40%', dir: 'down' });
    expect(formatChange(50.45, 0.1)).toEqual({ text: '▲ 0.10%', dir: 'up' });
    expect(formatChange(0, 0)).toEqual({ text: '0.00%', dir: 'flat' });
    expect(formatChange(null, null)).toEqual({ text: '–', dir: 'flat' });
    expect(formatChange(0.01, 0.0001)).toEqual({ text: '0.00%', dir: 'flat' });
    expect(priceLabel(12.3, 'INR', false)).toBe('₹12.30');
    expect(priceLabel(12.3, 'CAD', false)).toBe('CAD 12.30');
    expect(priceLabel(7561.67, 'USD', true)).toBe('7,561.67');
    expect(priceLabel(5, '', false)).toBe('5.00');
  });
  it('draws a sparkline inside its box, and nothing for a short series', () => {
    expect(sparkline([1])).toBe('');
    const pts = sparkline([5, 10, 7], 100, 28).split(' ').map((p) => p.split(',').map(Number) as [number, number]);
    expect(pts[0]?.[0]).toBe(0);
    expect(pts[2]?.[0]).toBe(100);
    expect(pts.every(([, y]) => y >= 0 && y <= 28)).toBe(true);
    expect(sparkline([3, 3, 3])).not.toContain('NaN');  // a flat series must not divide by zero
  });
});

describe('dollar moves and the detail numbers', () => {
  it('shows the move in money first, then percent', () => {
    expect(formatMove(-2.71, -0.36, 'USD')).toEqual({ text: '▼ $2.71 (0.36%)', dir: 'down' });
    expect(formatMove(1.5, 0.76, 'USD')).toEqual({ text: '▲ $1.50 (0.76%)', dir: 'up' });
    expect(formatMove(12, 0.5, 'CAD').text).toBe('▲ CAD 12.00 (0.50%)');
    expect(formatMove(0, 0, 'USD').dir).toBe('flat');
    expect(formatMove(null, null, 'USD').text).toBe('–');
  });
  it('formats the day range only when both ends are known', () => {
    expect(dayRange(99, 106, 'USD')).toBe('$99.00 – $106.00');
    expect(dayRange(null, 106, 'USD')).toBe('');
  });
  it('measures the 3-month change from the first and last close', () => {
    expect(historyChange([100, 110, 125])).toEqual({ change: 25, pct: 25 });
    expect(historyChange([100])).toBeUndefined();
    expect(historyChange([0, 5])).toBeUndefined();
  });
  it('reads the new quote fields and tolerates their absence', () => {
    const q = parseMarkets({ generated: 'g', tickers: [quote({ prev_close: 100, day_open: 101, day_high: 106, day_low: 99, history: [1, null, 2] })] })?.tickers[0];
    expect(q).toMatchObject({ prevClose: 100, dayOpen: 101, dayHigh: 106, dayLow: 99, history: [1, 2] });
    expect(parseMarkets({ generated: 'g', tickers: [quote()] })?.tickers[0]).toMatchObject({ dayOpen: null, history: [] });
  });
});

describe('market news', () => {
  it('accepts markets-feed stories and headlines about markets', () => {
    expect(isMarketNews({ title: 'Anything at all', subtopic: 'markets' })).toBe(true);
    expect(isMarketNews({ title: 'Stocks slip as Fed signals a pause' })).toBe(true);
    expect(isMarketNews({ title: 'Heating oil prices are up 59%' })).toBe(true);
    for (const t of ['Gold medal for the relay team', 'He shares his story of recovery', 'Fed up with traffic', 'Olive oil recipes']) expect(isMarketNews({ title: t })).toBe(false);
    expect(isMarketNews({ title: '‘I’m sick of flying’: I paid for priority boarding' })).toBe(false);
    expect(isMarketNews({ title: 'Ground stop followed updates to an older system' })).toBe(false);
  });
  it('also accepts a story naming something on your watchlist', () => {
    const parsed = parseMarkets({ generated: 'g', tickers: [quote({ symbol: 'NVDA', name: 'NVIDIA Corporation' }), quote({ symbol: 'TSLA', name: 'Tesla, Inc.' })] });
    const terms = watchTerms(parsed?.tickers ?? []);
    expect(terms.map((t) => t.source)).toEqual(expect.arrayContaining([expect.stringContaining('NVDA'), expect.stringContaining('NVIDIA'), expect.stringContaining('Tesla')]));
    expect(watchTerms(parseMarkets({ generated: 'g', tickers: [quote({ symbol: 'GOOGL', name: 'Alphabet Inc. Class A' })] })?.tickers ?? []).some((t) => t.test('Alphabet unveils a chip'))).toBe(true);
    expect(isMarketNews({ title: 'Why NVIDIA is rethinking its China plans' }, terms)).toBe(true);
    expect(isMarketNews({ title: 'TSLAX is not it' }, terms)).toBe(false);  // a symbol must stand alone
    expect(isMarketNews({ title: 'A quiet day in town' }, terms)).toBe(false);
  });
});
