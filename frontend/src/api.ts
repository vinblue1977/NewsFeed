import { parseFeed } from './feed';
import type { Feed } from './types';
import { type Articles, parseArticles } from './article';
import { type Markets, parseMarkets } from './markets';
import { WATCH_KEY } from './settings';
import { parseWeather, type Weather } from './weather';

export const FEED_URL = '/data/feed.json';

export async function loadFeed(signal?: AbortSignal): Promise<Feed> {
  const response = await fetch(FEED_URL, { cache: 'no-cache', signal });
  if (!response.ok) throw new Error(`feed ${response.status}`);
  const feed = parseFeed(await response.json());
  if (!feed) throw new Error('feed is not valid');
  return feed;
}

export const WEATHER_URL = '/data/weather.json';

/** The weather, or undefined for any problem: the strip is optional and must never break the page. */
export async function loadWeather(): Promise<Weather | undefined> {
  try {
    const response = await fetch(WEATHER_URL, { cache: 'no-cache' });
    return response.ok ? parseWeather(await response.json()) : undefined;
  } catch {
    return undefined;
  }
}

/** The quotes file name: the SHA-256 of the key, as the ingest names it, so the key itself never appears in a URL. */
export async function watchFile(key: string): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(key));
  return `watch-${[...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, '0')).join('')}`;
}

/** The private watchlist quotes, or undefined (no key, a bad key or any problem). */
export async function loadWatchlist(key: string): Promise<Markets | undefined> {
  if (!WATCH_KEY.test(key)) return undefined;
  try {
    const response = await fetch(`/data/${await watchFile(key)}.json`, { cache: 'no-cache' });
    return response.ok ? parseMarkets(await response.json()) : undefined;
  } catch {
    return undefined;
  }
}

export const ARTICLES_URL = '/data/articles.json';
const ARTICLES_MAX_AGE_MS = 60_000;
let cached: { at: number; articles: Articles } | undefined;
let inflight: Promise<Articles | undefined> | undefined;

async function fetchArticles(now: number): Promise<Articles | undefined> {
  try {
    const response = await fetch(ARTICLES_URL, { cache: 'no-cache' });
    const articles = response.ok ? parseArticles(await response.json()) : undefined;
    if (articles) cached = { at: now, articles };
    return articles ?? cached?.articles;
  } catch {
    return cached?.articles;
  }
}

/** The full-text articles, fetched on demand (only when a story that has full text is opened). A copy under a minute
 * old is reused, unless it lacks the article being asked for (a newer ingest may have added it). Simultaneous calls share
 * one request. Undefined for any problem: the Reader then shows the summary. */
export function loadArticles(id?: string, now = Date.now()): Promise<Articles | undefined> {
  if (cached && now - cached.at < ARTICLES_MAX_AGE_MS && (id === undefined || id in cached.articles)) {
    return Promise.resolve(cached.articles);
  }
  inflight ??= fetchArticles(now).finally(() => { inflight = undefined; });
  return inflight;
}

/** For tests: forget what was fetched. */
export function resetArticlesCache(): void {
  cached = undefined;
  inflight = undefined;
}

export const WATCHLIST_API = '/api/watchlist';

/** Read (no `symbols`) or replace the saved watchlist symbols. Resolves to the saved list, or undefined for any problem
 * (a wrong key answers 403). The key goes in the request body, never in a URL. */
export async function watchlistSymbols(key: string, symbols?: string[]): Promise<string[] | undefined> {
  if (!WATCH_KEY.test(key)) return undefined;
  try {
    const response = await fetch(WATCHLIST_API, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(symbols ? { key, symbols } : { key }),
    });
    if (!response.ok) return undefined;
    const saved = ((await response.json()) as { symbols?: unknown }).symbols;
    return Array.isArray(saved) && saved.every((v) => typeof v === 'string') ? (saved as string[]) : undefined;
  } catch {
    return undefined;
  }
}
