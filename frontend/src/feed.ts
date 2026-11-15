import type { Cluster, Feed, Item, Topic } from './types';

export const TOPICS: { id: Topic | 'all'; label: string }[] = [
  { id: 'all', label: 'For you' },
  { id: 'us', label: 'US' },
  { id: 'world', label: 'World' },
  { id: 'india', label: 'India' },
  { id: 'sports', label: 'Sports' },
  { id: 'tech', label: 'Technology' },
  { id: 'business', label: 'Business' },
];

/** Topics with a tab of their own: `stories(feed, 'all')` (For You, Browse, the briefing) leaves them out. */
const TAB_ONLY_TOPICS: ReadonlySet<string> = new Set(['local']);
const LABELS = new Map<string, string>([...TOPICS.map((t) => [t.id, t.label] as const), ['local', 'Local']]);
const STALE_AFTER_MS = 3 * 60 * 60 * 1000;
export const DAY_MS = 24 * 60 * 60 * 1000;

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

const IMAGE_NAME = /^[0-9a-f]{16}\.(jpg|png|webp)$/;

/** Where a story's picture is served from (our own site), or undefined. Only names of the exact shape the ingest writes are used. */
export function imageSrc(item: Item): string | undefined {
  return typeof item.img === 'string' && IMAGE_NAME.test(item.img) ? `/data/img/${item.img}` : undefined;
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
 * topic, the newest member in this topic does. Unclustered items stand alone.
 * `all` is every topic except the tab-only ones (local), which only their own topic returns. */
export function stories(feed: Feed, topic: Topic | 'all'): Story[] {
  const wanted = (i: Item) => (topic === 'all' ? !TAB_ONLY_TOPICS.has(i.topic) : i.topic === topic);
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
    if (topic === 'all' && TAB_ONLY_TOPICS.has(c.topic)) continue;  // a local cluster stays in the Local tab, whatever else joined it
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

/** How old a story is. Unparseable dates give NaN (never "recent"); a date in the future counts as just now. */
function ageMs(iso: string, now: Date): number {
  return Math.max(0, now.getTime() - new Date(iso).getTime());
}

/** Stories from the last day (an unparseable date is not recent). */
function recentOnly(list: Story[], now: Date): Story[] {
  return list.filter((s) => ageMs(s.item.published, now) < DAY_MS);
}

/** `list` (newest first) split into the last 24 hours and everything older; stories with an unparseable date come last. */
export function splitRecent(list: Story[], now: Date): { recent: Story[]; earlier: Story[] } {
  const recent: Story[] = [];
  const earlier: Story[] = [];
  const undated: Story[] = [];
  for (const s of list) {
    const age = ageMs(s.item.published, now);
    (Number.isNaN(age) ? undated : age < DAY_MS ? recent : earlier).push(s);
  }
  return { recent, earlier: [...earlier, ...undated] };
}

/** The lead story: the best-covered cluster from the last day (ties: newest). */
export function topStory(list: Story[], now: Date): Story | undefined {
  return [...recentOnly(list, now)].sort((a, b) => b.sources - a.sources || b.item.published.localeCompare(a.item.published))[0];
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

export interface BriefGroup {
  label: string;
  color: string;
  stories: Story[];
}

/** `list` without the top story (and the rest of its cluster), so it is not shown twice on one screen. */
function withoutTop(list: Story[], top: Story | undefined): Story[] {
  return list.filter((s) => s.item.id !== top?.item.id && !(top?.cluster && s.cluster?.id === top.cluster.id));
}

export const BRIEF_TOP_COLOR = '#5b86c9';
const BRIEF_GROUPS: { label: string; color: string; topics: Topic[] }[] = [
  { label: 'US', color: '#5b86c9', topics: ['us'] },
  { label: 'World · India', color: '#3fb6a8', topics: ['world', 'india'] },
  { label: 'Sports', color: '#6fbf5c', topics: ['sports'] },
  { label: 'Technology · Business', color: '#8a6fe0', topics: ['tech', 'business'] },
];
const MORE_GROUP = { label: 'More', color: '#9aa0a6' };  // any topic the groups above do not name, so no story is lost
const PER_GROUP = 3;

/** The Briefing: the lead story, then the newest few stories per topic group from the last day. Text only, no repeats. */
export function briefing(feed: Feed, now: Date): { top: Story | undefined; groups: BriefGroup[]; total: number } {
  const recent = recentOnly(stories(feed, 'all'), now);
  const top = topStory(recent, now);
  const rest = withoutTop(recent, top);
  const named = new Set<string>(BRIEF_GROUPS.flatMap((g) => g.topics));
  const groups = [
    ...BRIEF_GROUPS.map(({ label, color, topics }) => ({ label, color, stories: rest.filter((s) => topics.includes(s.item.topic)) })),
    { ...MORE_GROUP, stories: rest.filter((s) => !named.has(s.item.topic)) },
  ]
    .map((g) => ({ ...g, stories: g.stories.slice(0, PER_GROUP) }))
    .filter((g) => g.stories.length > 0);
  return { top, groups, total: (top ? 1 : 0) + groups.reduce((n, g) => n + g.stories.length, 0) };
}

export const SECTION_TOPICS: { topic: Topic; color: string }[] = [
  { topic: 'us', color: '#5b86c9' },
  { topic: 'world', color: '#3fb6a8' },
  { topic: 'india', color: '#e0a53f' },
  { topic: 'sports', color: '#6fbf5c' },
  { topic: 'tech', color: '#8a6fe0' },
  { topic: 'business', color: '#c97aa8' },
];
export const PER_SECTION = 3;  // the lead plus two more

export interface Section {
  topic: Topic;
  label: string;
  color: string;
  lead: Story;
  more: Story[];
  total: number;  // stories in the topic, so "See all" can say how many
}

/** For You, grouped by topic: in each, a lead (the newest story that has a picture, else the newest) and the next few.
 * `list` is newest first; the story shown as the top story is left out so it does not appear twice. */
export function sections(list: Story[], top: Story | undefined): Section[] {
  const rest = withoutTop(list, top);
  return SECTION_TOPICS.flatMap(({ topic, color }) => {
    const here = rest.filter((s) => s.item.topic === topic);
    const lead = here.find((s) => imageSrc(s.item)) ?? here[0];
    if (!lead) return [];
    return [{ topic, label: topicLabel(topic), color, lead, more: here.filter((s) => s !== lead).slice(0, PER_SECTION - 1), total: here.length }];
  });
}

export type Route = { kind: 'home' } | { kind: 'local' } | { kind: 'discovery'; sub?: string } | { kind: 'markets' } | { kind: 'settings' } | { kind: 'quote'; id: string } | { kind: 'story'; id: string } | { kind: 'read'; id: string };

/** The screen named by the URL hash: "#/story/<cluster id>", "#/read/<item id>", "#/local", "#/discovery", "#/discovery/<sub-topic>", "#/markets", "#/settings", "#/quote/<symbol>", anything else is the home screen. */
export function parseRoute(hash: string): Route {
  if (hash === '#/local') return { kind: 'local' };
  if (hash === '#/discovery') return { kind: 'discovery' };
  const d = /^#\/discovery\/([a-z0-9-]{1,30})$/.exec(hash);
  if (d?.[1]) return { kind: 'discovery', sub: d[1] };
  if (hash === '#/markets') return { kind: 'markets' };
  if (hash === '#/settings') return { kind: 'settings' };
  const q = /^#\/quote\/(.{1,40})$/.exec(hash);
  if (q?.[1]) {
    try {
      const id = decodeURIComponent(q[1]);
      if (/^[A-Za-z0-9^][A-Za-z0-9.^=_-]{0,14}$/.test(id)) return { kind: 'quote', id: id.toUpperCase() };
    } catch {
      return { kind: 'home' };  // a malformed escape
    }
    return { kind: 'home' };
  }
  const m = /^#\/(story|read)\/([A-Za-z0-9_-]{1,64})$/.exec(hash);
  if (!m?.[2]) return { kind: 'home' };
  return m[1] === 'story' ? { kind: 'story', id: m[2] } : { kind: 'read', id: m[2] };
}

const SUBTOPIC_LABELS: Record<string, string> = { nfl: 'NFL', nba: 'NBA', nhl: 'NHL', f1: 'F1' };

/** A sub-topic id ("cricket") as a title ("Cricket"). */
export function subtopicLabel(id: string): string {
  return SUBTOPIC_LABELS[id] ?? id.charAt(0).toUpperCase() + id.slice(1);
}

export interface Corner {
  id: string;
  label: string;
  lead: Story;  // the newest story in it
  total: number;
}

export const DISCOVERY_PER_SECTION = 5;
export const MAX_CORNERS = 8;

/** What the Browse screen (internally Discovery) shows, from `list` (newest first; local stories are not in it, they have their own tab).
 * - widely: stories from the last day that several sources cover, most sources first (ties: newest); the For You top story is left out
 * - justIn: the newest stories from the last day not already above
 * - corners: each sub-topic (cricket, markets...) with its newest story and its story count, the most recently active first, at most MAX_CORNERS. These use every story
 *   in the feed (any age, top story included), so a tile's count matches the list it opens. */
export function discovery(list: Story[], now: Date): { widely: Story[]; justIn: Story[]; corners: Corner[] } {
  const rest = recentOnly(withoutTop(list, topStory(list, now)), now);
  const widely = rest
    .filter((s) => s.sources > 1)
    .sort((a, b) => b.sources - a.sources || b.item.published.localeCompare(a.item.published))
    .slice(0, DISCOVERY_PER_SECTION);
  const seen = new Set(widely);
  const justIn = rest.filter((s) => !seen.has(s)).slice(0, DISCOVERY_PER_SECTION);
  const byId = new Map<string, Corner>();
  for (const s of list) {
    const id = s.item.subtopic;
    if (!id) continue;
    const have = byId.get(id);
    if (have) have.total += 1;
    else byId.set(id, { id, label: subtopicLabel(id), lead: s, total: 1 });
  }
  return { widely, justIn, corners: [...byId.values()].sort((a, b) => b.lead.item.published.localeCompare(a.lead.item.published) || b.total - a.total).slice(0, MAX_CORNERS) };
}

/** Where a story leads: the Story screen when several sources cover it, otherwise the Reader. Both are inside the app. */
export function storyLink(story: Story): string {
  return story.cluster && story.sources > 1 ? `#/story/${story.cluster.id}` : `#/read/${story.item.id}`;
}

/** The Reader's article and, if other sources cover the same story, the cluster to link to. */
export function readerPage(feed: Feed, itemId: string): { item: Item; coverageId: string | undefined } | undefined {
  const item = feed.items.find((i) => i.id === itemId);
  if (!item) return undefined;
  const cluster = item.cluster ? feed.clusters.find((c) => c.id === item.cluster) : undefined;
  if (!cluster) return { item, coverageId: undefined };
  const sources = new Set(feed.items.filter((i) => i.cluster === cluster.id).map((i) => i.source)).size;
  return { item, coverageId: sources > 1 ? cluster.id : undefined };
}

export interface StoryPage {
  cluster: Cluster;
  items: Item[];
  sources: number;  // distinct sources among the articles actually present
  related: Story[];
}

/** Everything the Story screen shows: the articles in the cluster (newest first) and a few other stories on the topic. */
export function storyPage(feed: Feed, clusterId: string, relatedLimit = 3): StoryPage | undefined {
  const cluster = feed.clusters.find((c) => c.id === clusterId);
  if (!cluster) return undefined;
  const items = feed.items.filter((i) => i.cluster === clusterId).sort((a, b) => b.published.localeCompare(a.published));
  if (items.length === 0) return undefined;
  const related = stories(feed, cluster.topic).filter((s) => s.cluster?.id !== clusterId).slice(0, relatedLimit);
  return { cluster, items, sources: new Set(items.map((i) => i.source)).size, related };
}
