import { afterEach, describe, expect, it, vi } from 'vitest';

import { FEED_URL, loadFeed, loadWeather } from './api';

const reply = (body: unknown, ok = true, status = 200) => vi.fn().mockResolvedValue({ ok, status, json: () => Promise.resolve(body) });

afterEach(() => vi.unstubAllGlobals());

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
