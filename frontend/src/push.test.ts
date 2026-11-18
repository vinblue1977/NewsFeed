import { describe, expect, it } from 'vitest';

import { DEFAULT_PUSH, keyBytes, parsePushPrefs, pushState, readSubscription, registration, validTime, vapidReady, type PushEnv } from './push';

const env = (over: Partial<PushEnv> = {}): PushEnv => ({
  hasServiceWorker: true, hasPushManager: true, hasNotification: true, permission: 'default', standalone: true, ios: true, subscribed: false, keyReady: true, ...over,
});

describe('push state', () => {
  it('asks an iPhone browser tab to install the app first', () => {
    expect(pushState(env({ standalone: false }))).toBe('needs-install');
    expect(pushState(env({ standalone: false, ios: false }))).toBe('off');
  });
  it('reports unsupported, blocked, no key, off and enabled', () => {
    expect(pushState(env({ hasPushManager: false }))).toBe('unsupported');
    expect(pushState(env({ permission: 'denied' }))).toBe('blocked');
    expect(pushState(env({ keyReady: false }))).toBe('no-key');
    expect(pushState(env())).toBe('off');
    expect(pushState(env({ permission: 'granted', subscribed: true }))).toBe('enabled');
    expect(pushState(env({ permission: 'granted', subscribed: false }))).toBe('off');
  });
});

describe('vapid key', () => {
  it('rejects the placeholder and accepts a real-looking public key', () => {
    expect(vapidReady()).toBe(false);
    expect(vapidReady('x')).toBe(false);
    expect(vapidReady('B'.repeat(87))).toBe(true);
  });
  it('turns a URL-safe base64 key into bytes', () => {
    expect([...keyBytes('AQID')]).toEqual([1, 2, 3]);
    expect([...keyBytes('-_8')]).toEqual([251, 255]);
  });
});

describe('times', () => {
  it('accepts only HH:MM', () => {
    expect(['00:00', '07:05', '23:59'].every(validTime)).toBe(true);
    expect(['24:00', '7:00', '07:60', '', 'x', 700, null].some(validTime)).toBe(false);
  });
});

describe('preferences', () => {
  it('defaults to every topic, weather on and quiet 22:00-07:00', () => {
    expect(parsePushPrefs(undefined)).toEqual(DEFAULT_PUSH);
    expect(parsePushPrefs('junk')).toEqual(DEFAULT_PUSH);
    expect(DEFAULT_PUSH).toEqual({ topics: ['us', 'world', 'india', 'sports', 'local'], weather: true, quietStart: '22:00', quietEnd: '07:00' });
  });
  it('keeps what is valid and drops the rest, in the fixed topic order', () => {
    expect(parsePushPrefs({ topics: ['local', 'us', 'bogus', 7], weather: false, quietStart: '23:30', quietEnd: '25:00' }))
      .toEqual({ topics: ['us', 'local'], weather: false, quietStart: '23:30', quietEnd: '07:00' });
    expect(parsePushPrefs({ topics: [] }).topics).toEqual([]);
  });
});

describe('registration', () => {
  const sub = { endpoint: 'https://push.example/abc', keys: { p256dh: 'P', auth: 'A' } };
  it('builds exactly the agreed blob', () => {
    expect(JSON.parse(registration(sub, { topics: ['us', 'sports'], weather: true, quietStart: '22:00', quietEnd: '07:00' }, 'America/Chicago')))
      .toEqual({ v: 1, subscription: sub, prefs: { topics: ['us', 'sports'], weather: true, quiet: { start: '22:00', end: '07:00' }, tz: 'America/Chicago' } });
  });
  it('reads a subscription and rejects incomplete or non-https ones', () => {
    expect(readSubscription({ endpoint: 'https://push.example/abc', keys: { p256dh: 'P', auth: 'A' }, expirationTime: null })).toEqual(sub);
    expect(readSubscription({ endpoint: 'http://push.example/abc', keys: { p256dh: 'P', auth: 'A' } })).toBeUndefined();
    expect(readSubscription({ endpoint: 'https://push.example/abc', keys: { p256dh: 'P' } })).toBeUndefined();
    expect(readSubscription(null)).toBeUndefined();
  });
});
