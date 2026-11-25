import type { Feed, Item } from './types';

/** Muted words: headlines that contain one are hidden everywhere in the app. Kept on the device as plain strings in settings. */
export const MAX_MUTED = 50;
export const MAX_MUTED_CHARS = 40;
export const MIN_MUTED_CHARS = 2;

const clean = (text: string): string => text.replace(/\s+/g, ' ').trim();
const same = (a: string, b: string): boolean => a.toLowerCase() === b.toLowerCase();

/** `text` cleaned up and added to the muted words; unchanged when it is too short or too long, already there (any case), or the list is full. */
export function withMutedWord(list: string[], text: string): string[] {
  const word = clean(text);
  if (word.length < MIN_MUTED_CHARS || word.length > MAX_MUTED_CHARS || list.length >= MAX_MUTED || list.some((w) => same(w, word))) return list;
  return [...list, word];
}

/** The words in `list` that are usable, cleaned up, once each (any case), at most MAX_MUTED: what is read back from a stored value. */
export function cleanMuted(list: string[]): string[] {
  return list.reduce(withMutedWord, [] as string[]);
}

const escapeRe = (s: string): string => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

/** A test for text containing any of the words as a whole word or phrase, in any case: "Trump" matches "Trump's" but not "Trumpet". */
export function mutedTest(words: string[]): (text: string) => boolean {
  if (words.length === 0) return () => false;
  const re = new RegExp(`(^|[^\\p{L}\\p{N}])(?:${words.map((w) => escapeRe(w).replace(/ /g, '\\s+')).join('|')})(?:['’]?s)?(?![\\p{L}\\p{N}])`, 'iu');  // a space in a phrase matches any run of white space; a plural ("tariffs") counts
  return (text) => re.test(text);
}

/** The feed with only `items`. Clusters keep the sources still present and disappear when none are. */
export function keepItems(feed: Feed, items: Item[]): Feed {
  const byCluster = new Map<string, Set<string>>();
  for (const i of items) if (i.cluster) byCluster.set(i.cluster, (byCluster.get(i.cluster) ?? new Set()).add(i.source));
  const clusters = feed.clusters.flatMap((c) => {
    const here = byCluster.get(c.id);
    return here ? [{ ...c, sources: here.size }] : [];
  });
  return { ...feed, items, clusters };
}

/** The feed without the stories that mention a muted word in the headline or summary. A cluster whose own headline mentions one goes
 * entirely, so a story about the muted subject cannot come back through another outlet's wording. */
export function withoutMuted(feed: Feed, words: string[]): Feed {
  if (words.length === 0) return feed;
  const hit = mutedTest(words);
  const gone = new Set(feed.clusters.filter((c) => hit(c.title)).map((c) => c.id));
  return keepItems(feed, feed.items.filter((i) => !hit(i.title) && !hit(i.summary) && !(i.cluster && gone.has(i.cluster))));  // apart, so a phrase cannot match across the two
}
