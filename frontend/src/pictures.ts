import { imageSrc } from './feed';
import type { Feed } from './types';

export const WARM_COUNT = 24;  // the newest stories with a picture: what the first screens show

/** The picture addresses of the newest stories, newest first, without repeats. */
export function warmList(feed: Feed, count = WARM_COUNT): string[] {
  const out: string[] = [];
  const sorted = [...feed.items].sort((a, b) => b.published.localeCompare(a.published));
  for (const item of sorted) {
    const src = imageSrc(item);
    if (src && !out.includes(src)) out.push(src);
    if (out.length >= count) break;
  }
  return out;
}

let last = '';
let latest: Feed | undefined;

/** Asks the service worker to keep the newest pictures for offline use (once per feed version; not on Data Saver or offline). */
export function warmPictures(feed: Feed): void {
  latest = feed;
  try {
    const nav = navigator as Navigator & { connection?: { saveData?: boolean } };
    if (nav.onLine === false || nav.connection?.saveData === true || feed.generated === last) return;
    const worker = nav.serviceWorker?.controller;
    if (!worker) return;
    worker.postMessage({ type: 'warm', urls: warmList(feed) });
    last = feed.generated;  // only once handed over, so a failed attempt is tried again
  } catch {
    /* warming is a nicety: never let it touch the app */
  }
}

/** The connection is back: the feed on screen may have been loaded on a dead signal, so its pictures are asked for again. */
export function warmAgain(): void {
  last = '';
  if (latest) warmPictures(latest);
}

export function resetWarmed(): void {
  last = '';
  latest = undefined;
}
