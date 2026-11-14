import { describe as suite, expect, it } from 'vitest';

import { degrees, describe, isFresh, parseWeather } from './weather';

const NOW = new Date('2026-11-13T12:00:00Z');
const doc = (over: Record<string, unknown> = {}) => ({
  generated: '2026-11-13T11:50:00+00:00',
  current: { temp: 34.1, feels_like: 25.3, code: 61, is_day: true },
  daily: [{ high: 43.6, low: 33.3 }],
  alerts: [{ id: 'a1', event: 'Wind Advisory', severity: 'Moderate' }],
  alerts_ok: true,
  ...over,
});

suite('parseWeather', () => {
  it('reduces the document to what the strip shows', () => {
    expect(parseWeather(doc())).toEqual({
      generated: '2026-11-13T11:50:00+00:00', temp: 34.1, code: 61, isDay: true, high: 43.6, low: 33.3,
      alerts: [{ event: 'Wind Advisory' }], alertsOk: true,
    });
  });

  it('tolerates gaps: no daily, no alerts, odd values', () => {
    const w = parseWeather(doc({ daily: [], alerts: [null, { id: 'z', event: '' }, { event: 'Flood Watch' }], alerts_ok: 'yes' }));
    expect(w?.high).toBeNull();
    expect(w?.alerts).toEqual([{ event: 'Flood Watch' }]);
    expect(w?.alertsOk).toBe(false);
    expect(parseWeather(doc({ current: { temp: 1, is_day: 'x', code: null } }))?.isDay).toBeNull();
    expect(parseWeather(doc({ alerts: 'none', daily: 'none' }))?.alerts).toEqual([]);
  });

  it('rejects anything that is not a forecast', () => {
    expect(parseWeather(null)).toBeUndefined();
    expect(parseWeather({})).toBeUndefined();
    expect(parseWeather(doc({ current: { temp: null } }))).toBeUndefined();
    expect(parseWeather(doc({ generated: 5 }))).toBeUndefined();
  });
});

suite('helpers', () => {
  it('hides an old or unreadable forecast', () => {
    expect(isFresh('2026-11-13T11:00:00Z', NOW)).toBe(true);
    expect(isFresh('2026-11-13T08:59:00Z', NOW)).toBe(false);
    expect(isFresh('garbage', NOW)).toBe(false);
    expect(isFresh('2026-11-13T12:03:00Z', NOW)).toBe(true);
    expect(isFresh('2026-11-13T13:00:00Z', NOW)).toBe(false);
  });

  it('describes weather codes', () => {
    expect(describe(0, true).label).toBe('Sunny');
    expect(describe(0, false).icon).toBe('🌙');
    expect(describe(1, true).label).toBe('Mostly sunny');
    expect(describe(1, false).icon).toBe('🌙');
    expect(describe(2, null).label).toBe('Partly cloudy');
    expect(describe(3, null).label).toBe('Overcast');
    expect(describe(45, null).label).toBe('Fog');
    expect(describe(53, null).label).toBe('Drizzle');
    expect(describe(56, null).label).toBe('Freezing drizzle');
    expect(describe(66, null).label).toBe('Freezing rain');
    expect(describe(61, null).label).toBe('Rain');
    expect(describe(65, null).label).toBe('Heavy rain');
    expect(describe(73, null).label).toBe('Snow');
    expect(describe(81, null).label).toBe('Showers');
    expect(describe(86, null).label).toBe('Snow showers');
    expect(describe(95, null).label).toBe('Thunderstorm');
    expect(describe(null, null).label).toBe('Weather');
    expect(describe(42, null).label).toBe('Weather');
  });

  it('rounds degrees', () => {
    expect(degrees(34.6)).toBe('35°');
    expect(degrees(null)).toBe('–');
  });
});
