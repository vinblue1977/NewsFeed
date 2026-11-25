import { DEFAULT_PUSH, parsePushPrefs, type PushPrefs } from './push';
import { cleanFollows } from './follow';
import { cleanMuted, keepItems } from './mute';
import type { Feed } from './types';

/** On-device preferences. Nothing here leaves the phone. */

export interface Settings {
  hiddenSources: string[];
  hiddenTickers: string[];
  mutedWords: string[];  // headlines containing one of these (as a whole word or phrase) are hidden everywhere (see mute.ts)
  watchCollapsed: boolean;  // the Markets watchlist list is folded away
  scheduleCollapsed: boolean;  // the Sports tab's My schedule card is folded away
  earningsCollapsed: boolean;  // the Markets upcoming earnings card is folded away
  cornersCollapsed: boolean;  // Browse's Corners of the feed tiles are folded away
  kernelCollapsed: boolean;  // the Technology list's Linux kernel table is folded to its header
  following: string[];  // followed sub-topics and keywords (see follow.ts); shown as the Following section under For you's top story
  teamColors: boolean;  // the Sports tab takes its accent and background from the first team in My teams
  myTeams: string[];  // teams, countries or players to follow on the Sports tab, matched by name
  scoresCollapsed: string[];  // sports (nfl, tennis, cricket) whose scores are folded away under All on the Sports tab
  watchKey: string;  // names the private watchlist file; empty when not set
  push: PushPrefs;  // which notifications to ask for; copied by hand to the server with the registration (docs/PUSH.md)
}

export const SETTINGS_KEY = 'news.settings';
export const WATCH_KEY = /^[a-z0-9]{16,64}$/;
export const DEFAULTS: Settings = { hiddenSources: [], hiddenTickers: [], mutedWords: [], watchCollapsed: false, earningsCollapsed: false, cornersCollapsed: false, kernelCollapsed: false, scheduleCollapsed: false, scoresCollapsed: [], following: [], teamColors: true, myTeams: [], watchKey: '', push: DEFAULT_PUSH };
export const SCORE_SPORTS = ['nfl', 'tennis', 'cricket'] as const;
export const MAX_TEAMS = 20;
export const MAX_TEAM_CHARS = 40;
const MAX_LIST = 200;  // a corrupted or hand-edited store cannot grow without bound

const strings = (v: unknown): string[] =>
  Array.isArray(v) ? [...new Set(v.filter((x): x is string => typeof x === 'string' && x !== '' && x.length <= 100))].slice(0, MAX_LIST) : [];

/** Settings from whatever was stored; anything unreadable falls back to the defaults. */
export function parseSettings(raw: string | null): Settings {
  if (!raw) return DEFAULTS;
  try {
    const v = JSON.parse(raw) as Partial<Record<keyof Settings, unknown>> | null;
    if (!v || typeof v !== 'object') return DEFAULTS;
    const key = typeof v.watchKey === 'string' && WATCH_KEY.test(v.watchKey) ? v.watchKey : '';
    return { hiddenSources: strings(v.hiddenSources), hiddenTickers: strings(v.hiddenTickers), mutedWords: cleanMuted(strings(v.mutedWords)), watchCollapsed: v.watchCollapsed === true, earningsCollapsed: v.earningsCollapsed === true, cornersCollapsed: v.cornersCollapsed === true, kernelCollapsed: v.kernelCollapsed === true, scheduleCollapsed: v.scheduleCollapsed === true, scoresCollapsed: strings(v.scoresCollapsed).filter((x) => (SCORE_SPORTS as readonly string[]).includes(x)), following: cleanFollows(strings(v.following)), teamColors: v.teamColors !== false, myTeams: strings(v.myTeams).reduce(withTeam, [] as string[]), watchKey: key, push: parsePushPrefs(v.push) };
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

/** `list` with `name` added or removed. */
export function toggled(list: string[], name: string): string[] {
  return list.includes(name) ? list.filter((x) => x !== name) : [...list, name].slice(-MAX_LIST);
}

/** The feed without the hidden sources. Clusters keep only the sources still present and disappear when none are. */
export function withoutSources(feed: Feed, hidden: string[]): Feed {
  if (hidden.length === 0) return feed;
  const off = new Set(hidden);
  return keepItems(feed, feed.items.filter((i) => !off.has(i.source)));
}

/** Every source in the feed, A to Z, plus any hidden one that is not in the current feed (so it can be switched back on). */
export function sourceNames(feed: Feed | undefined, hidden: string[]): string[] {
  return [...new Set([...(feed?.items.map((i) => i.source) ?? []), ...hidden])].sort((a, b) => a.localeCompare(b));
}

/** How many of the `all` entries are not hidden (a hidden entry that is no longer listed is not counted). */
export const shownCount = (all: string[], hidden: string[]): number => all.filter((a) => !hidden.includes(a)).length;

/** `name` cleaned up and added to the followed teams; unchanged when it is empty, too long, already there (any case) or the list is full. */
export function withTeam(teams: string[], name: string): string[] {
  const clean = name.replace(/\s+/g, ' ').trim();
  if (!clean || clean.length > MAX_TEAM_CHARS || teams.length >= MAX_TEAMS || teams.some((t) => t.toLowerCase() === clean.toLowerCase())) return teams;
  return [...teams, clean];
}
