/** "New since you last looked": when the app was last used is kept on this phone only (localStorage), never sent anywhere.
 *  A divider shows only for a gap of 10 minutes to 24 hours: a shorter one is the same sitting, a longer one means nearly
 *  everything is new, so a divider would say nothing. */
import type { KeyValue } from './briefing';
import type { Story } from './feed';

const KEY = 'news.lastVisit';
export const MIN_GAP_MS = 10 * 60_000;
export const MAX_GAP_MS = 24 * 3_600_000;

function store(): KeyValue | undefined {
  try {
    return globalThis.localStorage;  // blocked or missing storage: no divider, nothing else changes
  } catch {
    return undefined;
  }
}

export function loadLastVisit(kv: KeyValue | undefined = store()): number | undefined {
  try {
    const n = Number(kv?.getItem(KEY));
    return Number.isFinite(n) && n > 0 ? n : undefined;
  } catch {
    return undefined;
  }
}

export function saveVisit(at: number, kv: KeyValue | undefined = store()): void {
  try {
    kv?.setItem(KEY, String(at));
  } catch {
    /* not remembered; fine */
  }
}

/** The time to count "new" from, or undefined when the gap since `previous` is too short, too long, or unknown (first visit). */
export function sinceWhen(previous: number | undefined, now: number): number | undefined {
  if (previous === undefined) return undefined;
  const gap = now - previous;
  return gap >= MIN_GAP_MS && gap <= MAX_GAP_MS ? previous : undefined;
}

const isNew = (s: Story, since: number) => new Date(s.item.published).getTime() > since;

/** How many of `list` are new, and how many are not. A story with an unparseable date counts as not new. */
export function countNew(list: Story[], since: number): { fresh: number; seen: number } {
  const fresh = list.filter((s) => isNew(s, since)).length;
  return { fresh, seen: list.length - fresh };
}

/** In a list that is newest first: the index to put the divider before (the first story that is not new), or -1 for no
 *  divider, which is when nothing is new or nothing older is shown below. */
export function dividerAt(list: Story[], since: number): number {
  const at = list.findIndex((s) => !isNew(s, since));
  return at > 0 ? at : -1;
}

/** "3 new since you last looked · 6:12 PM", or the short form "3 new · 6:12 PM" for the divider inside a topic section. */
export function dividerLabel(fresh: number, since: number, locale?: string, short = false): string {
  const time = new Date(since).toLocaleTimeString(locale, { hour: 'numeric', minute: '2-digit' });
  return `${fresh} new${short ? '' : ' since you last looked'} · ${time}`;
}
