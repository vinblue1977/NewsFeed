export interface Weather {
  generated: string;
  temp: number;
  code: number | null;
  isDay: boolean | null;
  high: number | null;
  low: number | null;
  alerts: { event: string }[];
  alertsOk: boolean;
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
  };
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
