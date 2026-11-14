import { parseFeed } from './feed';
import type { Feed } from './types';
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
