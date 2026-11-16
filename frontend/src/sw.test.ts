import source from '../public/sw.js?raw';
import { describe, expect, it, vi } from 'vitest';

type Handler = (event: unknown) => void;

/** Loads public/sw.js against a fake service worker scope and returns its fetch handler. */
function load(match: (key: unknown) => Promise<unknown> = () => Promise.resolve(undefined)) {
  const handlers: Record<string, Handler> = {};
  const put = vi.fn(() => Promise.resolve());
  const cache = { put, keys: () => Promise.resolve([]), delete: () => Promise.resolve(true) };
  const scope = { location: { origin: 'https://n.example' }, addEventListener: (t: string, h: Handler) => { handlers[t] = h; }, skipWaiting: () => undefined, clients: { claim: () => Promise.resolve() } };
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
  return { run, put, fetchFn };
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
