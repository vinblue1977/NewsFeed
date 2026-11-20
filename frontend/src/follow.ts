import { subtopicLabel, subtopicOf, subtopicRoute, type Story } from './feed';

/** Followed topics and keywords, kept on the device as plain strings in settings: "topic:gadgets" or "kw:US election,midterms". */
export const FOLLOW_PER_GROUP = 5;
export const MAX_FOLLOWS = 20;
export const MAX_WORDS = 8;
export const MAX_WORD_CHARS = 40;

export type Follow = { kind: 'topic'; id: string } | { kind: 'keyword'; words: string[] };

export const topicKey = (id: string): string => `topic:${id}`;

/** The words of a keyword follow typed as "US election, midterms": trimmed, spaces collapsed, no duplicates (any case). Empty when none are usable. */
export function keywordWords(text: string): string[] {
  const out: string[] = [];
  for (const part of text.split(',')) {
    const w = part.replace(/\s+/g, ' ').trim();
    if (w.length < 2 || w.length > MAX_WORD_CHARS || out.some((x) => x.toLowerCase() === w.toLowerCase())) continue;
    out.push(w);
  }
  return out.slice(0, MAX_WORDS);
}

/** The stored key for a keyword follow, or undefined when `text` has no usable word. */
export function keywordKey(text: string): string | undefined {
  const words = keywordWords(text);
  return words.length > 0 ? `kw:${words.join(',')}` : undefined;
}

/** What a stored key means, or undefined when it is not a follow we understand (a hand-edited or corrupted store). */
export function parseFollow(key: string): Follow | undefined {
  if (key.startsWith('topic:')) {
    const id = key.slice(6);
    return /^[a-z][a-z0-9-]{0,30}$/.test(id) ? { kind: 'topic', id } : undefined;
  }
  if (key.startsWith('kw:')) {
    const words = keywordWords(key.slice(3));
    return words.length > 0 ? { kind: 'keyword', words } : undefined;
  }
  return undefined;
}

/** `list` with `key` added (unless full) or removed. */
export function toggleFollow(list: string[], key: string): string[] {
  if (list.includes(key)) return list.filter((k) => k !== key);
  return list.length >= MAX_FOLLOWS ? list : [...list, key];
}

/** The follows in `list` that are readable, in their canonical spelling, once each, at most MAX_FOLLOWS. */
export function cleanFollows(list: string[]): string[] {
  const seen = new Map<string, string>();  // lower-case key -> first spelling
  for (const k of list) {
    const f = parseFollow(k);
    if (!f) continue;
    const key = f.kind === 'topic' ? topicKey(f.id) : `kw:${f.words.join(',')}`;
    if (!seen.has(key.toLowerCase())) seen.set(key.toLowerCase(), key);
  }
  return [...seen.values()].slice(0, MAX_FOLLOWS);
}

export function followLabel(f: Follow): string {
  return f.kind === 'topic' ? subtopicLabel(f.id) : (f.words[0] ?? '');
}

const escapeRe = (s: string): string => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

/** A test for a story's headline or summary containing any of the words, each at the start of a word ("election" finds "elections", not "selection"). */
function wordTest(words: string[]): (s: Story) => boolean {
  const re = new RegExp(`(^|[^\\p{L}\\p{N}])(${words.map((w) => escapeRe(w.toLowerCase())).join('|')})`, 'u');
  return (s) => re.test(`${s.item.title} ${s.item.summary}`.toLowerCase());
}

export interface FollowGroup {
  key: string;
  label: string;
  stories: Story[];  // the newest few not already shown above
  total: number;  // every match
  route?: string;  // where "See all" goes: a followed topic's own list; a keyword has none
}

/** One group per follow, in the order followed, with the FOLLOW_PER_GROUP newest matches (`pool` is newest first) that no earlier group,
 * and none of the `skip` ids, already shows. A follow with nothing new to show is left out. */
export function followGroups(following: string[], pool: Story[], skip: ReadonlySet<string> = new Set()): FollowGroup[] {
  const shown = new Set(skip);
  const out: FollowGroup[] = [];
  for (const key of following) {
    const f = parseFollow(key);
    if (!f) continue;
    const test = f.kind === 'topic' ? (s: Story) => subtopicOf(s.item) === f.id : wordTest(f.words);
    const matched = pool.filter(test);
    const fresh = matched.filter((s) => !shown.has(s.item.id)).slice(0, FOLLOW_PER_GROUP);
    const first = matched[0];
    if (fresh.length === 0 || !first) continue;
    for (const s of fresh) shown.add(s.item.id);
    out.push({ key, label: followLabel(f), stories: fresh, total: matched.length, route: f.kind === 'topic' ? subtopicRoute(first.item.topic, f.id) : undefined });
  }
  return out;
}
