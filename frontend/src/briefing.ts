/** Which of today's briefing stories have been opened. Kept on this phone only (localStorage); the day it was saved for is
 *  stored with it, so tomorrow starts empty. */
export interface KeyValue {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
}

const KEY = 'news.briefing';

/** The local calendar day, e.g. 2026-11-17. */
export function dayKey(now: Date): string {
  const p = (n: number) => String(n).padStart(2, '0');
  return `${now.getFullYear()}-${p(now.getMonth() + 1)}-${p(now.getDate())}`;
}

function store(): KeyValue | undefined {
  try {
    return globalThis.localStorage;  // blocked or missing storage: the briefing still works, progress just is not kept
  } catch {
    return undefined;
  }
}

export function loadRead(day: string, kv: KeyValue | undefined = store()): string[] {
  try {
    const v: unknown = JSON.parse(kv?.getItem(KEY) ?? 'null');
    if (typeof v !== 'object' || v === null) return [];
    const o = v as { day?: unknown; ids?: unknown };
    if (o.day !== day || !Array.isArray(o.ids)) return [];
    return o.ids.filter((x): x is string => typeof x === 'string');
  } catch {
    return [];
  }
}

/** The ids read today, plus `id`. */
export function markRead(day: string, id: string, kv: KeyValue | undefined = store()): string[] {
  const ids = loadRead(day, kv);
  if (ids.includes(id)) return ids;
  const next = [...ids, id];
  try {
    kv?.setItem(KEY, JSON.stringify({ day, ids: next }));
  } catch {
    /* not remembered; fine */
  }
  return next;
}
