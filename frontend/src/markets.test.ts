import { describe, expect, it } from 'vitest';

import { formatChange, formatPrice, isFresh, parseMarkets, priceLabel, sparkline } from './markets';

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
  it('rejects documents without a stamp or without any readable quote', () => {
    expect(parseMarkets(null)).toBeUndefined();
    expect(parseMarkets({ indexes: [quote()] })).toBeUndefined();
    expect(parseMarkets({ generated: 'g', indexes: [{ symbol: 'x', ok: false }], tickers: 'nope' })).toBeUndefined();
    expect(parseMarkets({ generated: 'g', indexes: [null, 5, quote({ price: 'NaN' })] })).toBeUndefined();
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
