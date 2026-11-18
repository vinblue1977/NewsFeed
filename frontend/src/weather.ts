export interface Weather {
  generated: string;
  temp: number;
  code: number | null;
  isDay: boolean | null;
  high: number | null;
  low: number | null;
  alerts: { event: string }[];
  alertsOk: boolean;
  hourly: Hour[];
}

/** One forecast hour. `time` is local to the place, as Open-Meteo returns it ("2026-11-13T16:00"), never converted. */
export interface Hour {
  time: string;
  temp: number | null;
  pop: number | null;  // chance of precipitation, percent
  code: number | null;
}

const MAX_AGE_MS = 3 * 60 * 60 * 1000;
const CLOCK_SKEW_MS = 5 * 60 * 1000;

const num = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) ? v : null);
const text = (v: unknown): string => (typeof v === 'string' ? v : '');

/** The weather document, reduced to what the strip shows; undefined if it does not look like one. */
export function parseWeather(value: unknown): Weather | undefined {
  const v = value as Record<string, unknown> | null;
  const current = v?.current as Record<string, unknown> | undefined;
  const day = Array.isArray(v?.daily) ? (v.daily[0] as Record<string, unknown> | undefined) : undefined;
  const temp = num(current?.temp);
  if (!v || typeof v.generated !== 'string' || temp === null) return undefined;
  const alerts = Array.isArray(v.alerts) ? v.alerts : [];
  return {
    generated: v.generated,
    temp,
    code: num(current?.code),
    isDay: typeof current?.is_day === 'boolean' ? current.is_day : null,
    high: num(day?.high),
    low: num(day?.low),
    alerts: alerts.map((a: Record<string, unknown> | null) => ({ event: text(a?.event) })).filter((a) => a.event !== ''),
    alertsOk: v.alerts_ok === true,
    hourly: parseHours(v.hourly),
  };
}

const HOUR = /^\d{4}-\d{2}-\d{2}T([01]\d|2[0-3])/;

function parseHours(value: unknown): Hour[] {
  if (!Array.isArray(value)) return [];
  const out: Hour[] = [];
  for (const h of value as (Record<string, unknown> | null)[]) {
    if (typeof h?.time !== 'string' || !HOUR.test(h.time)) continue;
    out.push({ time: h.time, temp: num(h.temp), pop: num(h.pop), code: num(h.code) });
  }
  return out;
}

/** A forecast older than this is hidden rather than shown as if it were current. */
export function isFresh(generated: string, now: Date): boolean {
  const age = now.getTime() - new Date(generated).getTime();
  return age > -CLOCK_SKEW_MS && age < MAX_AGE_MS;  // NaN (an unreadable date) and a date far in the future are not fresh
}

/** WMO weather code -> a short description and an icon (a moon for a clear night). */
export function describe(code: number | null, isDay: boolean | null): { label: string; icon: string } {
  const night = isDay === false;
  if (code === null) return { label: 'Weather', icon: '🌡' };
  if (code === 0) return night ? { label: 'Clear', icon: '🌙' } : { label: 'Sunny', icon: '☀️' };
  if (code === 1) return night ? { label: 'Mostly clear', icon: '🌙' } : { label: 'Mostly sunny', icon: '🌤' };
  if (code === 2) return { label: 'Partly cloudy', icon: '⛅' };
  if (code === 3) return { label: 'Overcast', icon: '☁️' };
  if (code === 45 || code === 48) return { label: 'Fog', icon: '🌫' };
  if (code === 56 || code === 57) return { label: 'Freezing drizzle', icon: '🌧' };
  if (code >= 51 && code <= 55) return { label: 'Drizzle', icon: '🌦' };
  if (code === 66 || code === 67) return { label: 'Freezing rain', icon: '🌧' };
  if (code >= 61 && code <= 65) return { label: code === 65 ? 'Heavy rain' : 'Rain', icon: '🌧' };
  if (code >= 71 && code <= 77) return { label: 'Snow', icon: '❄️' };
  if (code >= 80 && code <= 82) return { label: 'Showers', icon: '🌦' };
  if (code === 85 || code === 86) return { label: 'Snow showers', icon: '🌨' };
  if (code >= 95 && code <= 99) return { label: 'Thunderstorm', icon: '⛈' };
  return { label: 'Weather', icon: '🌡' };
}

export const degrees = (n: number | null): string => (n === null ? '–' : `${Math.round(n)}°`);

/** The chance of precipitation (percent) from which an hour counts as wet. */
export const WET = 50;

const isSnow = (code: number | null): boolean => code !== null && ((code >= 71 && code <= 77) || code === 85 || code === 86);
const wet = (h: Hour): boolean => h.pop !== null && h.pop >= WET;
const dry = (h: Hour): boolean => h.pop !== null && h.pop < WET;

/** "2026-11-13T16" for the device's clock, comparable as text with an hour's `time` (the forecast is for where the user is). */
function hourKey(now: Date): string {
  const p = (n: number) => String(n).padStart(2, '0');
  return `${now.getFullYear()}-${p(now.getMonth() + 1)}-${p(now.getDate())}T${p(now.getHours())}`;
}

const isCurrent = (h: Hour, now: Date): boolean => h.time.slice(0, 13) === hourKey(now);

/** The next `count` forecast hours, starting with the current one. */
export function nextHours(hourly: Hour[], now: Date, count: number): Hour[] {
  const key = hourKey(now);
  return hourly.filter((h) => h.time.slice(0, 13) >= key).slice(0, count);
}

/** "4 PM", "12 AM": read from the text, so no time zone can shift it. */
export function hourLabel(time: string): string {
  if (!HOUR.test(time)) return '';
  const h = Number(time.slice(11, 13));
  return `${h % 12 === 0 ? 12 : h % 12} ${h < 12 ? 'AM' : 'PM'}`;
}

const OUTLOOK_HOURS = 12;

/** The one-line headline: when rain (or snow) starts or ends in the next 12 hours, else "Dry all day", else the current condition. */
export function headline(w: Weather, now: Date): string {
  const hours = nextHours(w.hourly, now, OUTLOOK_HOURS);
  const first = hours[0];
  if (first && isCurrent(first, now) && wet(first)) {  // only the present hour counts as "now": a stale forecast may start later
    const noun = isSnow(first.code) ? 'Snow' : 'Rain';
    const end = hours.find((h) => dry(h));
    return end ? `${noun} ends around ${hourLabel(end.time)}` : `${noun} likely to continue`;
  }
  const start = hours.find((h) => wet(h));
  if (start) return `${isSnow(start.code) ? 'Snow' : 'Rain'} starts around ${hourLabel(start.time)}`;
  if (hours.some((h) => dry(h))) return now.getHours() >= 17 || now.getHours() < 6 ? 'Dry tonight' : 'Dry all day';
  return describe(w.code, w.isDay).label;  // no precipitation data: do not claim a dry day
}

/** A short suggestion, or '' when there is nothing useful to say. */
export function tip(w: Weather, now: Date): string {
  const rain = nextHours(w.hourly, now, OUTLOOK_HOURS).some((h) => wet(h) && !isSnow(h.code));
  if (w.temp < 45) return rain ? 'Jacket and umbrella' : 'Bring a jacket';
  if (rain) return 'Umbrella';
  if (w.low !== null && w.low < 32) return 'Cold night ahead';
  return '';
}

export interface HourBar {
  label: string;
  temp: number | null;
  pop: number;  // 0-100, for the bar
  first: boolean;  // the first wet hour of the strip
}

/** The expanded strip: the next 7 hours. */
export function hourBars(hourly: Hour[], now: Date, count = 7): HourBar[] {
  const hours = nextHours(hourly, now, count);
  const firstWet = hours.findIndex((h) => wet(h));
  return hours.map((h, i) => ({
    label: isCurrent(h, now) ? 'Now' : hourLabel(h.time),
    temp: h.temp,
    pop: Math.max(0, Math.min(100, h.pop ?? 0)),
    first: i === firstWet,
  }));
}
