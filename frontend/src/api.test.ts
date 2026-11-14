import { afterEach, describe, expect, it, vi } from 'vitest';

import { ARTICLES_URL, FEED_URL, loadArticles, loadFeed, loadWatchlist, loadWeather, resetArticlesCache, watchFile, watchlistSymbols } from './api';

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

describe('loadWatchlist', () => {
  const key = 'a1b2c3d4e5f6a7b8';
  it('names the file by the SHA-256 of the key', async () => {
    expect(await watchFile('abc')).toBe('watch-ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad');
  });
  it('returns the parsed quotes, or undefined for any problem', async () => {
    const quote = { symbol: 'AAA', ok: true, price: 1 };
    const fetchMock = reply({ generated: 'g', indexes: [], tickers: [quote] });
    vi.stubGlobal('fetch', fetchMock);
    expect((await loadWatchlist(key))?.tickers[0]?.price).toBe(1);
    const url = String(fetchMock.mock.calls[0]?.[0]);
    expect(url).toBe(`/data/${await watchFile(key)}.json`);
    expect(url).not.toContain(key);  // the key never goes into a URL
    expect((await loadWatchlist(key))?.missing).toBe(0);
    expect(await loadWatchlist('../feed')).toBeUndefined();  // a bad key never reaches a URL
    vi.stubGlobal('fetch', reply({}, false, 403));
    expect(await loadWatchlist(key)).toBeUndefined();
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('offline')));
    expect(await loadWatchlist(key)).toBeUndefined();
  });
});

describe('watchlistSymbols', () => {
  const key = 'a1b2c3d4e5f6a7b8';
  it('reads and saves through the endpoint, with the key in the body', async () => {
    const fetchMock = reply({ symbols: ['AAA'] });
    vi.stubGlobal('fetch', fetchMock);
    expect(await watchlistSymbols(key)).toEqual(['AAA']);
    expect(await watchlistSymbols(key, ['AAA'])).toEqual(['AAA']);
    const [url, init] = fetchMock.mock.calls[1] as [string, RequestInit];
    expect(url).toBe('/api/watchlist');
    expect(JSON.parse(init.body as string)).toEqual({ key, symbols: ['AAA'] });
  });
  it('is undefined for a bad key, a refusal, a bad answer or no network', async () => {
    expect(await watchlistSymbols('short')).toBeUndefined();
    vi.stubGlobal('fetch', reply({ error: 'forbidden' }, false, 403));
    expect(await watchlistSymbols(key)).toBeUndefined();
    vi.stubGlobal('fetch', reply({ symbols: [1] }));
    expect(await watchlistSymbols(key)).toBeUndefined();
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('offline')));
    expect(await watchlistSymbols(key)).toBeUndefined();
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
