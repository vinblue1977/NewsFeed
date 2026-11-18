/** Web Push: the pieces that need no browser. The phone's subscription and these preferences are copied by hand into AWS SSM
 *  (see docs/PUSH.md): there is no public endpoint, so nothing here is sent anywhere. */

/** The VAPID PUBLIC key (not a secret; the private half is only in SSM, see docs/PUSH.md). A new key pair means a new value here. */
export const VAPID_PUBLIC_KEY = 'BGM25Kuslhx3XjZ9hm5Gc2Dp0odNpTmwXb3y4TCtZIE2AupggVcoRn7Iz53c4GEJzZeRNYq8rUaWNR7atv3Eabw';

export const PUSH_TOPICS = [
  { id: 'us', label: 'US' },
  { id: 'world', label: 'World' },
  { id: 'india', label: 'India' },
  { id: 'sports', label: 'Sports' },
  { id: 'local', label: 'Local' },
] as const;
export type PushTopic = (typeof PUSH_TOPICS)[number]['id'];

export interface PushPrefs {
  topics: PushTopic[];  // the news topics to push, in the order above
  weather: boolean;  // push National Weather Service alerts
  quietStart: string;  // "HH:MM", local time: no pushes from here...
  quietEnd: string;  // ...until here
}

export const DEFAULT_PUSH: PushPrefs = { topics: PUSH_TOPICS.map((t) => t.id), weather: true, quietStart: '22:00', quietEnd: '07:00' };

const TIME = /^([01]\d|2[0-3]):[0-5]\d$/;
export const validTime = (s: unknown): s is string => typeof s === 'string' && TIME.test(s);

/** Preferences from whatever was stored; anything unreadable falls back to the defaults. */
export function parsePushPrefs(v: unknown): PushPrefs {
  const o = (typeof v === 'object' && v !== null ? v : {}) as Record<string, unknown>;
  const given = o['topics'];
  const ids: string[] = Array.isArray(given) ? given.filter((x): x is string => typeof x === 'string') : PUSH_TOPICS.map((t) => t.id);
  const start = o['quietStart'];
  const end = o['quietEnd'];
  return {
    topics: PUSH_TOPICS.map((t) => t.id).filter((id) => ids.includes(id)),
    weather: typeof o['weather'] === 'boolean' ? o['weather'] : DEFAULT_PUSH.weather,
    quietStart: validTime(start) ? start : DEFAULT_PUSH.quietStart,
    quietEnd: validTime(end) ? end : DEFAULT_PUSH.quietEnd,
  };
}

/** The key in the form `pushManager.subscribe` wants. Throws on text that is not base64. */
export function keyBytes(key: string): Uint8Array<ArrayBuffer> {
  const pad = '='.repeat((4 - (key.length % 4)) % 4);
  const raw = atob((key + pad).replace(/-/g, '+').replace(/_/g, '/'));
  const out = new Uint8Array(raw.length);
  for (let n = 0; n < raw.length; n += 1) out[n] = raw.charCodeAt(n);
  return out;
}

/** True once the placeholder has been replaced with a real VAPID public key: 65 bytes, an uncompressed P-256 point (first byte 4). */
export function vapidReady(key: string = VAPID_PUBLIC_KEY): boolean {
  if (!/^[A-Za-z0-9_-]{86,88}$/.test(key)) return false;
  try {
    const bytes = keyBytes(key);
    return bytes.length === 65 && bytes[0] === 4;
  } catch {
    return false;
  }
}

/** Whether a subscription (made with `applicationServerKey`) belongs to this key: an old one after a key change does not. */
export function sameKey(applicationServerKey: ArrayBuffer | null | undefined, key: string = VAPID_PUBLIC_KEY): boolean {
  if (!applicationServerKey || !vapidReady(key)) return false;
  const have = new Uint8Array(applicationServerKey);
  const want = keyBytes(key);
  return have.length === want.length && have.every((b, n) => b === want[n]);
}

export interface PushEnv {
  hasServiceWorker: boolean;
  hasPushManager: boolean;
  hasNotification: boolean;
  permission: 'default' | 'granted' | 'denied';
  standalone: boolean;  // opened from the Home Screen icon
  ios: boolean;
  subscribed: boolean;
  keyReady: boolean;
}

export type PushState = 'unsupported' | 'needs-install' | 'no-key' | 'blocked' | 'off' | 'enabled';

/** Where notifications stand on this device, for the Settings message. */
export function pushState(e: PushEnv): PushState {
  if (e.ios && !e.standalone) return 'needs-install';  // iPhone only allows push for an app added to the Home Screen
  if (!e.hasServiceWorker || !e.hasPushManager || !e.hasNotification) return 'unsupported';
  if (e.permission === 'denied') return 'blocked';
  if (e.permission === 'granted' && e.subscribed) return 'enabled';
  return e.keyReady ? 'off' : 'no-key';
}

export interface Subscription {
  endpoint: string;
  keys: { p256dh: string; auth: string };
}

/** The push service's subscription as the registration needs it; undefined if it is incomplete. */
export function readSubscription(json: unknown): Subscription | undefined {
  const o = json as { endpoint?: unknown; keys?: { p256dh?: unknown; auth?: unknown } } | null;
  const endpoint = o?.endpoint;
  const p256dh = o?.keys?.p256dh;
  const auth = o?.keys?.auth;
  if (typeof endpoint !== 'string' || !endpoint.startsWith('https://') || typeof p256dh !== 'string' || typeof auth !== 'string' || !p256dh || !auth) return undefined;
  return { endpoint, keys: { p256dh, auth } };
}

/** The registration the user pastes into SSM. `tz` is the device's time zone, so quiet hours mean the user's own night. */
export function registration(sub: Subscription, prefs: PushPrefs, tz: string): string {
  return JSON.stringify({
    v: 1,
    subscription: sub,
    prefs: { topics: prefs.topics, weather: prefs.weather, quiet: { start: prefs.quietStart, end: prefs.quietEnd }, tz },
  });
}

/** The message for each state. */
export const PUSH_NOTES: Record<PushState, string> = {
  unsupported: 'This browser cannot receive notifications.',
  'needs-install': 'On iPhone, add the app to the Home Screen (Share, then Add to Home Screen) and open it from there to turn notifications on.',
  'no-key': 'Notifications are not set up yet: the app has no push key. See docs/PUSH.md.',
  blocked: 'Notifications are blocked. Allow them for this app in iOS Settings, then come back.',
  off: 'Notifications are off.',
  enabled: 'Notifications are on for this device.',
};
