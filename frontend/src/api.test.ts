import { afterEach, describe, expect, it, vi } from 'vitest';

import { ARTICLES_URL, FEED_URL, loadArticles, loadFeed, loadWeather, resetArticlesCache } from './api';

const reply = (body: unknown, ok = true, status = 200) => vi.fn().mockResolvedValue({ ok, status, json: () => Promise.resolve(body) });

afterEach(() => {
  vi.unstubAllGlobals();
  resetArticlesCache();
});

describe('loadFeed', () => {
  it('fetches and parses the feed without using a stale cache', async () => {
    const fetchMock = reply({ generated: 'g', items: [], clusters: [] });
    vi.stubGlobal('fetch', fetchMock);
    expect((await loadFeed()).generated).toBe('g');
    expect(fetchMock).toHaveBeenCalledWith(FEED_URL, expect.objectContaining({ cache: 'no-cache' }));
  });

  it('rejects an error response', async () => {
    vi.stubGlobal('fetch', reply({}, false, 503));
    await expect(loadFeed()).rejects.toThrow('feed 503');
  });

  it('rejects a body that is not a feed', async () => {
    vi.stubGlobal('fetch', reply({ nope: 1 }));
    await expect(loadFeed()).rejects.toThrow('not valid');
  });
});

describe('loadWeather', () => {
  it('returns the parsed weather', async () => {
    vi.stubGlobal('fetch', reply({ generated: 'g', current: { temp: 30 }, daily: [], alerts: [], alerts_ok: true }));
    expect((await loadWeather())?.temp).toBe(30);
  });

  it('gives undefined for a missing file, a bad body or a network error', async () => {
    vi.stubGlobal('fetch', reply({}, false, 403));
    expect(await loadWeather()).toBeUndefined();
    vi.stubGlobal('fetch', reply({ nope: 1 }));
    expect(await loadWeather()).toBeUndefined();
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('offline')));
    expect(await loadWeather()).toBeUndefined();
  });
});

describe('loadArticles', () => {
  const doc = { articles: { a: [{ t: 'p', x: 'Text' }] } };

  it('fetches once and reuses the answer for a minute', async () => {
    const fetchMock = reply(doc);
    vi.stubGlobal('fetch', fetchMock);
    expect(await loadArticles(undefined, 1_000)).toEqual({ a: [{ t: 'p', x: 'Text' }] });
    expect(await loadArticles(undefined, 30_000)).toBeDefined();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledWith(ARTICLES_URL, expect.objectContaining({ cache: 'no-cache' }));
    await loadArticles(undefined, 1_000 + 61_000);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it('keeps the last good copy when a later fetch fails', async () => {
    vi.stubGlobal('fetch', reply(doc));
    await loadArticles(undefined, 0);
    vi.stubGlobal('fetch', reply({}, false, 500));
    expect(await loadArticles(undefined, 120_000)).toBeDefined();
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('offline')));
    expect(await loadArticles(undefined, 240_000)).toBeDefined();
  });

  it('gives undefined when nothing has ever loaded', async () => {
    vi.stubGlobal('fetch', reply({}, false, 403));
    expect(await loadArticles()).toBeUndefined();
    vi.stubGlobal('fetch', reply({ nope: 1 }));
    expect(await loadArticles()).toBeUndefined();
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('offline')));
    expect(await loadArticles()).toBeUndefined();
  });

  it('refetches when the requested article is missing from the cached copy, and shares one request', async () => {
    const first = { articles: { a: [{ t: 'p', x: 'A' }] } };
    const second = { articles: { a: [{ t: 'p', x: 'A' }], b: [{ t: 'p', x: 'B' }] } };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: true, status: 200, json: () => Promise.resolve(first) })
      .mockResolvedValueOnce({ ok: true, status: 200, json: () => Promise.resolve(second) });
    vi.stubGlobal('fetch', fetchMock);
    await loadArticles('a', 0);
    expect((await loadArticles('a', 5_000))?.b).toBeUndefined();  // present: served from the cache
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect((await loadArticles('b', 6_000))?.b).toBeDefined();  // missing: fetched again
    expect(fetchMock).toHaveBeenCalledTimes(2);
    resetArticlesCache();
    fetchMock.mockReset().mockResolvedValue({ ok: true, status: 200, json: () => Promise.resolve(second) });
    await Promise.all([loadArticles('a'), loadArticles('b')]);
    expect(fetchMock).toHaveBeenCalledTimes(1);  // simultaneous calls share one request
  });
});
