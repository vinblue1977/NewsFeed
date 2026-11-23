import { afterEach, describe, expect, it, vi } from 'vitest';

import { resetWarmed, warmAgain, warmList, warmPictures, WARM_COUNT } from './pictures';
import type { Feed } from './types';

const item = (n: number, img?: string) => ({ id: `i${n}`, title: `T${n}`, url: `https://x.example/${n}`, published: `2026-11-22T${String(10 + (n % 10)).padStart(2, '0')}:00:00+00:00`, source: 'S', topic: 'us', summary: '', cluster: 'c', ...(img ? { img } : {}) });
const name = (n: number) => `${n.toString(16).padStart(16, '0')}.jpg`;
const feed = (items: ReturnType<typeof item>[], generated = 'g1'): Feed => ({ generated, items: items as Feed['items'], clusters: [] });

afterEach(() => { vi.unstubAllGlobals(); resetWarmed(); });

describe('warmList', () => {
  it('lists the newest stories that have a picture, newest first, without repeats, up to the limit', () => {
    const items = [item(1, name(1)), item(2), item(3, name(3)), item(4, name(3)), item(5, 'not-a-picture.exe')];
    expect(warmList(feed(items))).toEqual([`/data/img/${name(3)}`, `/data/img/${name(1)}`]);  // 3 is newer than 1
    const many = Array.from({ length: 60 }, (_, n) => item(n, name(n)));
    expect(warmList(feed(many))).toHaveLength(WARM_COUNT);
  });
});

describe('warmPictures', () => {
  const stub = (over: object = {}) => {
    const postMessage = vi.fn();
    vi.stubGlobal('navigator', { onLine: true, serviceWorker: { controller: { postMessage } }, ...over });
    return postMessage;
  };

  it('posts the list to the service worker once per feed version', () => {
    const post = stub();
    warmPictures(feed([item(1, name(1))]));
    warmPictures(feed([item(1, name(1))]));
    expect(post).toHaveBeenCalledTimes(1);
    expect(post).toHaveBeenCalledWith({ type: 'warm', urls: [`/data/img/${name(1)}`] });
    warmPictures(feed([item(1, name(1))], 'g2'));
    expect(post).toHaveBeenCalledTimes(2);
  });

  it('does nothing offline, on Data Saver, or without a service worker', () => {
    const offline = stub({ onLine: false });
    warmPictures(feed([item(1, name(1))]));
    const saver = stub({ connection: { saveData: true } });
    warmPictures(feed([item(1, name(1))]));
    stub({ serviceWorker: { controller: null } });
    expect(() => warmPictures(feed([item(1, name(1))]))).not.toThrow();
    stub({ serviceWorker: undefined });
    expect(() => warmPictures(feed([item(1, name(1))]))).not.toThrow();
    expect(offline).not.toHaveBeenCalled();
    expect(saver).not.toHaveBeenCalled();
  });

  it('asks again when the connection returns, with the feed last seen', () => {
    const post = stub();
    warmPictures(feed([item(1, name(1))]));
    warmAgain();
    expect(post).toHaveBeenCalledTimes(2);
    resetWarmed();
    warmAgain();  // no feed seen yet: nothing to ask for
    expect(post).toHaveBeenCalledTimes(2);
  });

  it('is tried again later when it could not be handed over', () => {
    stub({ onLine: false });
    warmPictures(feed([item(1, name(1))]));
    const post = stub();
    warmPictures(feed([item(1, name(1))]));  // same feed version, now online
    expect(post).toHaveBeenCalledTimes(1);
  });

  it('never throws', () => {
    vi.stubGlobal('navigator', { get onLine(): boolean { throw new Error('x'); } });
    expect(() => warmPictures(feed([]))).not.toThrow();
  });
});
