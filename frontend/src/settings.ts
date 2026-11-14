import type { Feed } from './types';

/** On-device preferences. Nothing here leaves the phone. */
export type TextSize = 'small' | 'medium' | 'large';

export interface Settings {
  textSize: TextSize;
  hiddenSources: string[];
  hiddenTickers: string[];
  watchKey: string;  // names the private watchlist file; empty when not set
}

export const SETTINGS_KEY = 'news.settings';
export const WATCH_KEY = /^[a-z0-9]{16,64}$/;
export const DEFAULTS: Settings = { textSize: 'medium', hiddenSources: [], hiddenTickers: [], watchKey: '' };
export const TEXT_SIZES: { id: TextSize; label: string; px: number }[] = [
  { id: 'small', label: 'Small', px: 16 },
  { id: 'medium', label: 'Medium', px: 18 },
  { id: 'large', label: 'Large', px: 21 },
];
const MAX_LIST = 200;  // a corrupted or hand-edited store cannot grow without bound

const strings = (v: unknown): string[] =>
  Array.isArray(v) ? [...new Set(v.filter((x): x is string => typeof x === 'string' && x !== '' && x.length <= 100))].slice(0, MAX_LIST) : [];

/** Settings from whatever was stored; anything unreadable falls back to the defaults. */
export function parseSettings(raw: string | null): Settings {
  if (!raw) return DEFAULTS;
  try {
    const v = JSON.parse(raw) as Partial<Record<keyof Settings, unknown>> | null;
    if (!v || typeof v !== 'object') return DEFAULTS;
    const size = TEXT_SIZES.find((t) => t.id === v.textSize)?.id ?? DEFAULTS.textSize;
    const key = typeof v.watchKey === 'string' && WATCH_KEY.test(v.watchKey) ? v.watchKey : '';
    return { textSize: size, hiddenSources: strings(v.hiddenSources), hiddenTickers: strings(v.hiddenTickers), watchKey: key };
  } catch {
    return DEFAULTS;
  }
}

export function loadSettings(): Settings {
  try {
    return parseSettings(localStorage.getItem(SETTINGS_KEY));
  } catch {
    return DEFAULTS;  // storage can be blocked; the app works without it
  }
}

export function saveSettings(s: Settings): void {
  try {
    localStorage.setItem(SETTINGS_KEY, JSON.stringify(s));
  } catch {
    /* not remembered; fine */
  }
}

/** The reader's text size in px. */
export function readSize(size: TextSize): number {
  return TEXT_SIZES.find((t) => t.id === size)?.px ?? 18;
}

/** `list` with `name` added or removed. */
export function toggled(list: string[], name: string): string[] {
  return list.includes(name) ? list.filter((x) => x !== name) : [...list, name].slice(-MAX_LIST);
}

/** The feed without the hidden sources. Clusters keep only the sources still present and disappear when none are. */
export function withoutSources(feed: Feed, hidden: string[]): Feed {
  if (hidden.length === 0) return feed;
  const off = new Set(hidden);
  const items = feed.items.filter((i) => !off.has(i.source));
  const byCluster = new Map<string, Set<string>>();
  for (const i of items) if (i.cluster) byCluster.set(i.cluster, (byCluster.get(i.cluster) ?? new Set()).add(i.source));
  const clusters = feed.clusters.flatMap((c) => {
    const here = byCluster.get(c.id);
    return here ? [{ ...c, sources: here.size }] : [];
  });
  return { ...feed, items, clusters };
}

/** Every source in the feed, A to Z, plus any hidden one that is not in the current feed (so it can be switched back on). */
export function sourceNames(feed: Feed | undefined, hidden: string[]): string[] {
  return [...new Set([...(feed?.items.map((i) => i.source) ?? []), ...hidden])].sort((a, b) => a.localeCompare(b));
}
