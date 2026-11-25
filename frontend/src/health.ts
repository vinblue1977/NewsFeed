/** Source health for Settings: what the last ingest run said about each feed. Pure, so it is easy to test. */
import type { SourceStatus } from './types';

export type HealthState = 'failed' | 'empty' | 'ok';

export interface HealthRow {
  id: string;  // the id in backend/ingest/sources.py, the one to change to drop the source
  label: string;  // the publisher's name; a local feed is "Local feed N" (its host would give away the town)
  state: HealthState;
  note: string;  // what to read next to the label: "12 stories", "failed: HTTP 404", "0 stories (4 filtered)"
}

const ORDER: Record<HealthState, number> = { failed: 0, empty: 1, ok: 2 };
const MAX_ERROR = 60;

const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? '' : 's'}`;

function describe(s: SourceStatus): { state: HealthState; note: string } {
  if (!s.ok) return { state: 'failed', note: `failed${s.error ? `: ${s.error.slice(0, MAX_ERROR)}` : ''}` };
  const dupes = s.duplicates ? `${plural(s.duplicates, 'story')} already from another feed`.replace('storys', 'stories') : '';
  if (s.items === 0 && dupes) return { state: 'ok', note: `0 new (${dupes})` };  // it worked: another feed just had the stories first
  const dropped = [s.filtered ? `${s.filtered} filtered` : '', s.blocked ? `${s.blocked} blocked` : ''].filter(Boolean).join(', ');
  if (s.items === 0) return { state: 'empty', note: `0 stories${dropped ? ` (${dropped})` : ''}` };
  return { state: 'ok', note: plural(s.items, 'story').replace('storys', 'stories') };
}

const LOCAL_KINDS: Record<string, string> = { local: 'Local feed', 'local-official': 'Local official feed', 'local-alert': 'Local alert feed' };

/** The name to show: the publisher's, or for a local feed (its host would give away the town) "Local feed 1", numbered from its id
 * so the same feed keeps the same label whatever else is added or removed. */
function labelOf(id: string, s: SourceStatus): string {
  if (s.name) return s.name;
  const m = /^(local(?:-official|-alert)?)-(\d+)$/.exec(id);
  const kind = m?.[1] ? LOCAL_KINDS[m[1]] : undefined;
  return kind && m?.[2] ? `${kind} ${Number(m[2]) + 1}` : id;  // no name and not a local id: the id, never a wrong label
}

/** One row per source: failed first, then empty, then the rest by name (numbers in order: 2 before 10). */
export function sourceHealth(sources: Record<string, SourceStatus> | undefined): HealthRow[] {
  if (!sources) return [];
  return Object.entries(sources)
    .map(([id, s]) => ({ id, label: labelOf(id, s), ...describe(s) }))
    .sort((a, b) => ORDER[a.state] - ORDER[b.state] || a.label.localeCompare(b.label, undefined, { numeric: true }) || a.id.localeCompare(b.id));
}

export const needAttention = (rows: HealthRow[]): number => rows.filter((r) => r.state !== 'ok').length;
