import { describe as suite, expect, it } from 'vitest';

import { degrees, describe, headline, hourBars, hourLabel, isFresh, nextHours, parseWeather, tip, type Hour, type Weather } from './weather';

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
      alerts: [{ event: 'Wind Advisory' }], alertsOk: true, hourly: [],
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

const hour = (h: number, pop: number | null, over: Partial<Hour> = {}): Hour => ({
  time: `2026-11-13T${String(h).padStart(2, '0')}:00`,
  temp: 40,
  pop,
  code: 3,
  ...over,
});
const weather = (hourly: Hour[], over: Partial<Weather> = {}): Weather => ({
  generated: '2026-11-13T11:50:00+00:00', temp: 50, code: 3, isDay: true, high: 57, low: 40, alerts: [], alertsOk: true, hourly, ...over,
});
const at = (h: number) => new Date(2026, 10, 13, h, 20);  // local 13 Nov, h:20

suite('parseWeather hourly', () => {
  it('reads the hours and skips broken ones', () => {
    const w = parseWeather(doc({ hourly: [{ time: '2026-11-13T09:00', temp: 41, pop: 20, code: 3 }, { time: 5 }, null, { time: 'soon' }, { time: '2026-11-13T25:00' }, { time: '2026-11-13T10:00', temp: 'x', pop: null }] }));
    expect(w?.hourly).toEqual([
      { time: '2026-11-13T09:00', temp: 41, pop: 20, code: 3 },
      { time: '2026-11-13T10:00', temp: null, pop: null, code: null },
    ]);
    expect(parseWeather(doc({ hourly: 'none' }))?.hourly).toEqual([]);
  });
});

suite('hours', () => {
  it('labels hours from the text', () => {
    expect(hourLabel('2026-11-13T00:00')).toBe('12 AM');
    expect(hourLabel('2026-11-13T12:00')).toBe('12 PM');
    expect(hourLabel('2026-11-13T16:00')).toBe('4 PM');
    expect(hourLabel('nonsense')).toBe('');
  });
  it('starts at the current hour, even from a later clock minute', () => {
    const hs = [hour(9, 0), hour(10, 0), hour(11, 0), hour(12, 0)];
    expect(nextHours(hs, at(10), 2).map((h) => h.time.slice(11, 13))).toEqual(['10', '11']);
    expect(nextHours(hs, at(23), 3)).toEqual([]);
    expect(nextHours([], at(10), 3)).toEqual([]);
  });
});

suite('headline', () => {
  const dryDay = [hour(9, 5), hour(10, 10), hour(11, 20), hour(12, 30)];
  it('says when rain starts', () => {
    expect(headline(weather([hour(9, 10), hour(10, 30), hour(16, 60), hour(17, 80)]), at(9))).toBe('Rain starts around 4 PM');
  });
  it('says snow when the wet hour has a snow code', () => {
    expect(headline(weather([hour(9, 10), hour(10, 70, { code: 73 })]), at(9))).toBe('Snow starts around 10 AM');
    expect(headline(weather([hour(9, 70, { code: 85 }), hour(10, 10)]), at(9))).toBe('Snow ends around 10 AM');
  });
  it('says when rain ends, and when it does not within 12 hours', () => {
    expect(headline(weather([hour(9, 80), hour(10, 60), hour(11, 20), hour(12, 70)]), at(9))).toBe('Rain ends around 11 AM');
    expect(headline(weather([hour(9, 80), hour(10, 60)]), at(9))).toBe('Rain likely to continue');
  });
  it('says dry by day and tonight, and only past hours are ignored', () => {
    expect(headline(weather(dryDay), at(9))).toBe('Dry all day');
    expect(headline(weather([hour(19, 0), hour(20, 10)]), at(19))).toBe('Dry tonight');
    expect(headline(weather([hour(2, 0), hour(3, 10)]), at(2))).toBe('Dry tonight');
    expect(headline(weather([hour(8, 90), hour(10, 10)]), at(10))).toBe('Dry all day');
  });
  it('does not call a later hour "now" when the forecast starts late', () => {
    expect(headline(weather([hour(14, 80), hour(15, 20)]), at(11))).toBe('Rain starts around 2 PM');
  });
  it('treats exactly 50 as wet and 49 as dry', () => {
    expect(headline(weather([hour(9, 0), hour(10, 50)]), at(9))).toBe('Rain starts around 10 AM');
    expect(headline(weather([hour(9, 0), hour(10, 49)]), at(9))).toBe('Dry all day');
  });
  it('falls back to the current condition without precipitation data', () => {
    expect(headline(weather([]), at(9))).toBe('Overcast');
    expect(headline(weather([hour(9, null), hour(10, null)]), at(9))).toBe('Overcast');
  });
});

suite('tip', () => {
  it('suggests a jacket when it is cold now', () => {
    expect(tip(weather([hour(9, 0)], { temp: 41 }), at(9))).toBe('Bring a jacket');
  });
  it('combines the jacket and the umbrella when it is cold and rain is coming', () => {
    expect(tip(weather([hour(9, 0), hour(11, 80)], { temp: 40 }), at(9))).toBe('Jacket and umbrella');
  });
  it('suggests an umbrella for rain on a mild day, not for snow', () => {
    expect(tip(weather([hour(9, 0), hour(14, 70)], { temp: 55 }), at(9))).toBe('Umbrella');
    expect(tip(weather([hour(9, 0), hour(14, 70, { code: 73 })], { temp: 55, low: 40 }), at(9))).toBe('');
  });
  it('warns of a cold night, else says nothing', () => {
    expect(tip(weather([hour(9, 0)], { temp: 55, low: 30 }), at(9))).toBe('Cold night ahead');
    expect(tip(weather([hour(9, 0)], { temp: 55, low: 40 }), at(9))).toBe('');
    expect(tip(weather([], { temp: 55, low: null }), at(9))).toBe('');
  });
});

suite('hourBars', () => {
  it('lists seven hours, marks the first wet one and clamps the bars', () => {
    const hs = Array.from({ length: 10 }, (_, i) => hour(9 + i, i === 3 ? 140 : i === 4 ? 60 : i === 1 ? null : 10));
    const bars = hourBars(hs, at(9));
    expect(bars).toHaveLength(7);
    expect(bars[0]).toMatchObject({ label: 'Now', pop: 10, first: false });
    expect(bars[1]?.pop).toBe(0);
    expect(hourBars([hour(14, 10), hour(15, 10)], at(11))[0]?.label).toBe('2 PM');  // a forecast that starts late has no Now
    expect(bars[3]).toMatchObject({ label: '12 PM', pop: 100, first: true });
    expect(bars[4]?.first).toBe(false);
    expect(hourBars([], at(9))).toEqual([]);
  });
});
