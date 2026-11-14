import { parseFeed } from './feed';
import type { Feed } from './types';

export const FEED_URL = '/data/feed.json';

export async function loadFeed(signal?: AbortSignal): Promise<Feed> {
  const response = await fetch(FEED_URL, { cache: 'no-cache', signal });
  if (!response.ok) throw new Error(`feed ${response.status}`);
  const feed = parseFeed(await response.json());
  if (!feed) throw new Error('feed is not valid');
  return feed;
}
