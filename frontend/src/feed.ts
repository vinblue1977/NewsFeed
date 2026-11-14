import type { Cluster, Feed, Item, Topic } from './types';

export const TOPICS: { id: Topic | 'all'; label: string }[] = [
  { id: 'all', label: 'For you' },
  { id: 'us', label: 'US' },
  { id: 'world', label: 'World' },
  { id: 'india', label: 'India' },
  { id: 'sports', label: 'Sports' },
  { id: 'tech', label: 'Technology' },
  { id: 'business', label: 'Business' },
  { id: 'local', label: 'Local' },
];

const LABELS = new Map<string, string>(TOPICS.map((t) => [t.id, t.label]));
const STALE_AFTER_MS = 3 * 60 * 60 * 1000;

export function topicLabel(topic: string): string {
  return LABELS.get(topic) ?? topic;
}

/** Only web links are ever rendered as links; anything else in the feed is dropped to '#'. */
export function safeUrl(url: string): string {
  try {
    const u = new URL(url);
    return u.protocol === 'https:' || u.protocol === 'http:' ? u.href : '#';
  } catch {
    return '#';
  }
}

export function timeAgo(iso: string, now: Date): string {
  const minutes = Math.max(0, Math.floor((now.getTime() - new Date(iso).getTime()) / 60000));
  if (Number.isNaN(minutes)) return '';
  if (minutes < 60) return `${Math.max(1, minutes)} min ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} h ago`;
  return `${Math.floor(hours / 24)} d ago`;
}

export function isStale(generated: string, now: Date): boolean {
  return now.getTime() - new Date(generated).getTime() > STALE_AFTER_MS;
}

/** A stable colour for a source's round badge, so the same source always looks the same. */
export function badgeColor(source: string): string {
  let h = 0;
  for (const ch of source) h = (h * 31 + (ch.codePointAt(0) ?? 0)) % 360;
  return `hsl(${h} 38% 42%)`;
}

export function initial(source: string): string {
  return (source.trim()[0] ?? '?').toUpperCase();
}

const isText = (v: unknown): v is string => typeof v === 'string' && v !== '';

function validItem(v: unknown): v is Item {
  const i = v as Partial<Item> | null;
  return !!i && isText(i.id) && isText(i.title) && isText(i.url) && isText(i.published) && isText(i.source) && isText(i.topic);
}

function validCluster(v: unknown): v is Cluster {
  const c = v as Partial<Cluster> | null;
  return !!c && isText(c.id) && isText(c.lead) && Array.isArray(c.items) && typeof c.sources === 'number';
}

/** The feed if it has the right shape; entries that are malformed are dropped, so one bad item cannot blank the page. */
export function parseFeed(value: unknown): Feed | undefined {
  const v = value as Partial<Feed> | null;
  if (!v || typeof v.generated !== 'string' || !Array.isArray(v.items) || !Array.isArray(v.clusters)) return undefined;
  return { generated: v.generated, items: v.items.filter(validItem), clusters: v.clusters.filter(validCluster) };
}

export interface Story {
  item: Item;
  cluster: Cluster | undefined;
  sources: number;
}

/** One story per cluster, newest first. The cluster's lead item stands for it; if the lead is missing or in another
 * topic, the newest member in this topic does. Unclustered items stand alone. */
export function stories(feed: Feed, topic: Topic | 'all'): Story[] {
  const wanted = (i: Item) => topic === 'all' || i.topic === topic;
  const members = new Map<string, Item[]>();
  const loose: Item[] = [];
  for (const item of feed.items) {
    if (!wanted(item)) continue;
    if (item.cluster) members.set(item.cluster, [...(members.get(item.cluster) ?? []), item]);
    else loose.push(item);
  }
  const out: Story[] = loose.map((item) => ({ item, cluster: undefined, sources: 1 }));
  const known = new Set<string>();
  for (const c of feed.clusters) {
    known.add(c.id);
    const here = members.get(c.id) ?? [];
    const item = here.find((i) => i.id === c.lead) ?? [...here].sort((a, b) => b.published.localeCompare(a.published))[0];
    if (item) out.push({ item, cluster: c, sources: c.sources });
  }
  for (const [id, here] of members) {  // a cluster id the feed does not describe: still show the story
    const item = [...here].sort((a, b) => b.published.localeCompare(a.published))[0];
    if (!known.has(id) && item) out.push({ item, cluster: undefined, sources: 1 });
  }
  return out.sort((a, b) => b.item.published.localeCompare(a.item.published));
}

/** The lead story: the best-covered cluster from the last day (ties: newest). */
export function topStory(list: Story[], now: Date): Story | undefined {
  const day = 24 * 60 * 60 * 1000;
  const recent = list.filter((s) => now.getTime() - new Date(s.item.published).getTime() < day);
  return [...recent].sort((a, b) => b.sources - a.sources || b.item.published.localeCompare(a.item.published))[0];
}

/** The other articles in the lead story's cluster ("Full coverage"), best three, one per source. */
export function coverage(feed: Feed, story: Story, limit = 3): Item[] {
  if (!story.cluster) return [];
  const byId = new Map(feed.items.map((i) => [i.id, i]));
  const seen = new Set([story.item.source]);
  const out: Item[] = [];
  for (const id of story.cluster.items) {
    const item = byId.get(id);
    if (!item || seen.has(item.source)) continue;
    seen.add(item.source);
    out.push(item);
    if (out.length >= limit) break;
  }
  return out;
}
