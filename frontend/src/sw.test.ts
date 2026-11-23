import source from '../public/sw.js?raw';
import { describe, expect, it, vi } from 'vitest';

type Handler = (event: unknown) => void;

/** Loads public/sw.js against a fake service worker scope and returns its fetch handler. */
function load(match: (key: unknown) => Promise<unknown> = () => Promise.resolve(undefined)) {
  const handlers: Record<string, Handler> = {};
  const put = vi.fn(() => Promise.resolve());
  const cache = { put, match: () => Promise.resolve(undefined), keys: () => Promise.resolve([]), delete: () => Promise.resolve(true) };
  const showNotification = vi.fn(() => Promise.resolve());
  const openWindow = vi.fn(() => Promise.resolve());
  let windows: unknown[] = [];
  const scope = {
    location: { origin: 'https://n.example' },
    addEventListener: (t: string, h: Handler) => { handlers[t] = h; },
    skipWaiting: () => undefined,
    clients: { claim: () => Promise.resolve(), matchAll: () => Promise.resolve(windows), openWindow },
    registration: { showNotification },
  };
  const fakeCaches = { match, open: () => Promise.resolve(cache), keys: () => Promise.resolve([]), delete: () => Promise.resolve(true) };
  const fetchFn = vi.fn(() => Promise.resolve({ ok: true, clone() { return this; } }));
  // eslint-disable-next-line no-new-func -- the worker file is plain script, run here against a fake scope
  new Function('self', 'caches', 'fetch', source)(scope, fakeCaches, fetchFn);
  const run = (url: string, method = 'GET', mode = 'cors') => {
    const respondWith = vi.fn();
    const waitUntil = vi.fn();
    handlers['fetch']?.({ request: { url, method, mode }, respondWith, waitUntil });
    return { respondWith, waitUntil };
  };
  const push = (data: unknown) => {
    const waitUntil = vi.fn();
    const json = typeof data === 'function' ? data : () => data;
    handlers['push']?.({ data: data === undefined ? null : { json }, waitUntil });
    return waitUntil;
  };
  const click = async (url: unknown, open: unknown[] = []) => {
    windows = open;
    const close = vi.fn();
    const waitUntil = vi.fn();
    handlers['notificationclick']?.({ notification: { close, data: url === undefined ? undefined : { url } }, waitUntil });
    await waitUntil.mock.calls[0]?.[0];
    return close;
  };
  const message = (data: unknown, source: unknown = { url: 'https://n.example/' }) => {
    const waitUntil = vi.fn();
    handlers['message']?.({ data, source, waitUntil });
    return waitUntil;
  };
  return { run, put, fetchFn, push, click, message, showNotification, openWindow };
}

describe('service worker', () => {
  it('leaves the API, private files, other origins and non-GET requests alone', () => {
    const { run } = load();
    expect(run('https://n.example/api/watchlist').respondWith).not.toHaveBeenCalled();
    expect(run('https://n.example/data/watch-abc.json').respondWith).not.toHaveBeenCalled();
    expect(run('https://n.example/data/earn-abc.json').respondWith).not.toHaveBeenCalled();
    expect(run('https://other.example/data/feed.json').respondWith).not.toHaveBeenCalled();
    expect(run('https://n.example/data/feed.json', 'POST').respondWith).not.toHaveBeenCalled();
  });

  it('handles pages, data, assets and pictures', () => {
    const { run } = load();
    expect(run('https://n.example/', 'GET', 'navigate').respondWith).toHaveBeenCalled();
    expect(run('https://n.example/data/feed.json').respondWith).toHaveBeenCalled();
    expect(run('https://n.example/assets/a.js').respondWith).toHaveBeenCalled();
    expect(run('https://n.example/data/img/a.webp').respondWith).toHaveBeenCalled();
  });

  it('keeps a good data response in the background and serves the kept one when the network fails', async () => {
    const { run, fetchFn } = load();
    const first = run('https://n.example/data/feed.json');
    await first.respondWith.mock.calls[0]?.[0];
    expect(first.waitUntil).toHaveBeenCalled();

    const kept = { ok: true };
    const offline = load(() => Promise.resolve(kept));
    offline.fetchFn.mockImplementation(() => Promise.reject(new Error('offline')));
    const second = offline.run('https://n.example/data/feed.json');
    await expect(second.respondWith.mock.calls[0]?.[0]).resolves.toBe(kept);
    expect(fetchFn).toHaveBeenCalled();
  });

  it('rethrows when the network fails and nothing is kept', async () => {
    const t = load();
    t.fetchFn.mockImplementation(() => Promise.reject(new Error('offline')));
    const r = t.run('https://n.example/data/feed.json');
    await expect(r.respondWith.mock.calls[0]?.[0]).rejects.toThrow('offline');
  });
});

describe('picture warming', () => {
  const good = '/data/img/0123456789abcdef.jpg';

  it('fetches and keeps the pictures that are not kept yet', async () => {
    const t = load();
    const wait = t.message({ type: 'warm', urls: [good, '/data/img/fedcba9876543210.webp'] });
    await wait.mock.calls[0]?.[0];
    expect(t.fetchFn).toHaveBeenCalledTimes(2);
    expect(t.put).toHaveBeenCalledTimes(2);
  });

  it('takes only our own picture names, and ignores other messages', () => {
    const t = load();
    expect(t.message({ type: 'warm', urls: ['https://evil.example/a.jpg', '/api/watchlist', '/data/img/../x.jpg', 5] })).not.toHaveBeenCalled();
    expect(t.message({ type: 'other', urls: [good] })).not.toHaveBeenCalled();
    expect(t.message({ type: 'warm', urls: 'x' })).not.toHaveBeenCalled();
    expect(t.message(null)).not.toHaveBeenCalled();
  });

  it('ignores messages that do not come from a page of this app', () => {
    const t = load();
    const msg = { type: 'warm', urls: [good] };
    for (const source of [null, {}, { url: 'https://evil.example/' }, { url: 'not a url' }, { url: 5 }]) {
      expect(t.message(msg, source)).not.toHaveBeenCalled();
    }
  });

  it('accepts a page of this app at any path, query or hash', async () => {
    for (const url of ['https://n.example/', 'https://n.example/#/story/x', 'https://n.example/a/b?c=d']) {
      const t = load();
      const wait = t.message({ type: 'warm', urls: [good] }, { url });
      expect(wait).toHaveBeenCalledTimes(1);
      await wait.mock.calls[0]?.[0];
    }
  });

  it('skips the pictures already kept, and stops quietly when the network fails', async () => {
    const cache = { match: vi.fn(() => Promise.resolve({ ok: true })), put: vi.fn(), keys: () => Promise.resolve([]), delete: () => Promise.resolve(true) };
    const handlers: Record<string, Handler> = {};
    const fetchFn = vi.fn(() => Promise.reject(new Error('offline')));
    const scope = { location: { origin: 'https://n.example' }, addEventListener: (n: string, h: Handler) => { handlers[n] = h; }, skipWaiting: () => undefined };
    // eslint-disable-next-line no-new-func -- the worker file is plain script, run here against a fake scope
    new Function('self', 'caches', 'fetch', source)(scope, { open: () => Promise.resolve(cache), match: () => Promise.resolve(undefined) }, fetchFn);
    const waitUntil = vi.fn();
    handlers['message']?.({ data: { type: 'warm', urls: [good] }, source: { url: 'https://n.example/' }, waitUntil });
    await waitUntil.mock.calls[0]?.[0];
    expect(fetchFn).not.toHaveBeenCalled();  // already kept
    cache.match.mockImplementation(() => Promise.resolve(undefined as never));
    const again = vi.fn();
    handlers['message']?.({ data: { type: 'warm', urls: [good, good.replace('0', '1')] }, source: { url: 'https://n.example/' }, waitUntil: again });
    await expect(again.mock.calls[0]?.[0]).resolves.toBeUndefined();
    expect(fetchFn).toHaveBeenCalledTimes(1);  // the first failure ends the run
    expect(cache.put).not.toHaveBeenCalled();
  });

  it('keeps going when one put fails and still trims', async () => {
    const t = load();
    t.put.mockImplementation(() => Promise.reject(new Error('quota')));
    const wait = t.message({ type: 'warm', urls: [good, '/data/img/fedcba9876543210.webp'] });
    await wait.mock.calls[0]?.[0];
    expect(t.fetchFn).toHaveBeenCalledTimes(2);
  });
});

describe('push notifications', () => {
  it('shows the title, body and tag, and remembers where to go', async () => {
    const t = load();
    const wait = t.push({ title: 'Senate passes bill', body: '12 outlets', url: '/#/story/abc123', tag: 'abc123' });
    await wait.mock.calls[0]?.[0];
    expect(t.showNotification).toHaveBeenCalledWith('Senate passes bill', expect.objectContaining({ body: '12 outlets', tag: 'abc123', data: { url: '/#/story/abc123' } }));
  });

  it('still shows a generic notification for a missing, malformed or odd payload', async () => {
    for (const bad of [undefined, () => { throw new Error('not json'); }, null, 'text', 5]) {
      const t = load();
      const wait = t.push(bad);
      await wait.mock.calls[0]?.[0];
      expect(wait).toHaveBeenCalledTimes(1);
      expect(t.showNotification).toHaveBeenCalledWith('New story', expect.objectContaining({ body: '', data: { url: '/' } }));
    }
  });

  it('only opens story screens inside the app', async () => {
    for (const url of ['https://evil.example/', '//evil.example', '/#/settings', '/#/story/a b', '/#/local/x', `${'java'}script:alert(1)`, 7]) {
      const t = load();
      await t.push({ title: 't', url }).mock.calls[0]?.[0];
      expect(t.showNotification).toHaveBeenCalledWith('t', expect.objectContaining({ data: { url: '/' } }));
    }
    const t = load();
    await t.push({ title: 't', url: '/#/read/xyz_1-2' }).mock.calls[0]?.[0];
    expect(t.showNotification).toHaveBeenCalledWith('t', expect.objectContaining({ data: { url: '/#/read/xyz_1-2' } }));
  });

  it('also opens the root and the Local, Markets and Sports tabs', async () => {
    for (const url of ['/', '/#/local', '/#/markets', '/#/sports']) {
      const t = load();
      await t.push({ title: 't', url }).mock.calls[0]?.[0];
      expect(t.showNotification).toHaveBeenCalledWith('t', expect.objectContaining({ data: { url } }));
    }
  });

  it('drives the window the user is looking at first', async () => {
    const t = load();
    const hidden = { focused: false, visibilityState: 'hidden', focus: vi.fn(() => Promise.resolve()), navigate: vi.fn(() => Promise.resolve()) };
    const front = { focused: true, visibilityState: 'visible', focus: vi.fn(() => Promise.resolve()), navigate: vi.fn(() => Promise.resolve()) };
    await t.click('/#/story/abc', [hidden, front]);
    expect(front.navigate).toHaveBeenCalledWith('/#/story/abc');
    expect(hidden.navigate).not.toHaveBeenCalled();
  });

  it('limits long text and leaves the tag out when it is not a string', async () => {
    const t = load();
    await t.push({ title: 'x'.repeat(500), body: 'y'.repeat(900), tag: 3 }).mock.calls[0]?.[0];
    const [title, options] = t.showNotification.mock.calls[0] as unknown as [string, { body: string; tag?: string }];
    expect(title).toHaveLength(120);
    expect(options.body).toHaveLength(300);
    expect('tag' in options).toBe(false);
  });

  it('focuses an open window and goes to the story', async () => {
    const t = load();
    const w = { focus: vi.fn(() => Promise.resolve()), navigate: vi.fn(() => Promise.resolve()) };
    const close = await t.click('/#/story/abc', [w]);
    expect(close).toHaveBeenCalled();
    expect(w.focus).toHaveBeenCalled();
    expect(w.navigate).toHaveBeenCalledWith('/#/story/abc');
    expect(t.openWindow).not.toHaveBeenCalled();
  });

  it('tries the next window, then opens a new one, when a window cannot be driven', async () => {
    const t = load();
    const bad = { focus: vi.fn(() => Promise.resolve()), navigate: vi.fn(() => Promise.reject(new Error('no'))) };
    const good = { focus: vi.fn(() => Promise.resolve()), navigate: vi.fn(() => Promise.resolve()) };
    await t.click('/#/read/x', [bad, good]);
    expect(good.navigate).toHaveBeenCalledWith('/#/read/x');
    expect(t.openWindow).not.toHaveBeenCalled();
    const none = load();
    await none.click('/#/read/x', [bad]);
    expect(none.openWindow).toHaveBeenCalledWith('/#/read/x');
  });

  it('opens the app root when the notification carries no usable address', async () => {
    const t = load();
    await t.click(undefined);
    expect(t.openWindow).toHaveBeenCalledWith('/');
  });
});
