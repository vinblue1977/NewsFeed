/** Live scores from data/scores.json: NFL games, ATP tennis matches and cricket lines. Every field is checked: the file is
 * not trusted, and a bad entry is dropped rather than shown wrong. */
export type GameState = 'pre' | 'live' | 'final';

export interface Side {
  name: string;
  score: number | null;
}

export interface Game {
  id: string;
  state: GameState;
  detail: string;
  start: string;
  away: Side;
  home: Side;
  url: string | undefined;
}

export interface Player {
  name: string;
  sets: number[];
  winner: boolean;
}

export interface Match {
  id: string;
  state: GameState;
  detail: string;
  start: string;
  tournament: string;
  players: [Player, Player];
}

export interface CricketMatch {
  id: string;
  line: string;
  live: boolean;
  url: string | undefined;
}

export interface Scores {
  generated: string;
  nfl: Game[];
  tennis: Match[];
  cricket: CricketMatch[];
  down: Sport[];  // sports the ingest could not read this time
}

export type Sport = 'nfl' | 'tennis' | 'cricket';

const MAX_AGE_MS = 30 * 60 * 1000;
const CLOCK_SKEW_MS = 5 * 60 * 1000;
const MAX_TEXT = 80;  // names and details
const MAX_LINE = 200;  // cricket lines end with the score, and ids can be URLs: cut them at the backend's limit, not at a display width

const obj = (v: unknown): Record<string, unknown> | undefined => (v && typeof v === 'object' && !Array.isArray(v) ? (v as Record<string, unknown>) : undefined);
const str = (v: unknown, max = MAX_TEXT): string => (typeof v === 'string' ? v.slice(0, max) : '');
const num = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) ? v : null);
const state = (v: unknown): GameState | undefined => (v === 'pre' || v === 'live' || v === 'final' ? v : undefined);
const link = (v: unknown): string | undefined => {
  if (typeof v !== 'string') return undefined;
  try {
    const u = new URL(v);
    return u.protocol === 'https:' || u.protocol === 'http:' ? u.href : undefined;
  } catch {
    return undefined;
  }
};
const readable = (v: unknown): boolean => obj(v)?.ok === true;
const list = (v: unknown): unknown[] => {
  const entries = obj(v)?.entries;
  return obj(v)?.ok === true && Array.isArray(entries) ? entries : [];
};

function side(v: unknown): Side | undefined {
  const o = obj(v);
  const name = str(o?.name);
  return o && name ? { name, score: num(o.score) } : undefined;
}

function game(v: unknown): Game | undefined {
  const o = obj(v);
  const s = state(o?.state);
  const away = side(o?.away);
  const home = side(o?.home);
  const id = str(o?.id, MAX_LINE);
  return o && s && away && home && id ? { id, state: s, detail: str(o.detail), start: str(o.start), away, home, url: link(o.url) } : undefined;
}

function player(v: unknown): Player | undefined {
  const o = obj(v);
  const name = str(o?.name);
  if (!o || !name) return undefined;
  const sets = Array.isArray(o.sets) ? o.sets.map(num).filter((n): n is number => n !== null).slice(0, 5) : [];
  return { name, sets, winner: o.winner === true };
}

function match(v: unknown): Match | undefined {
  const o = obj(v);
  const s = state(o?.state);
  const players = Array.isArray(o?.players) ? o.players.map(player) : [];
  const [a, b] = players;
  const id = str(o?.id, MAX_LINE);
  return o && s && a && b && players.length === 2 && id ? { id, state: s, detail: str(o.detail), start: str(o.start), tournament: str(o.tournament), players: [a, b] } : undefined;
}

function cricket(v: unknown): CricketMatch | undefined {
  const o = obj(v);
  const id = str(o?.id, MAX_LINE);
  const line = str(o?.line, MAX_LINE);
  return o && id && line ? { id, line, live: o.live === true, url: link(o.url) } : undefined;
}

const ORDER: Record<GameState, number> = { live: 0, pre: 1, final: 2 };

/** Live first, then games still to come (soonest first), then finished ones (latest first). Start times are compared as
 * dates, not strings, and an unreadable one sorts last. */
export function byState<T extends { state: GameState; start: string }>(items: T[]): T[] {
  const at = (t: T, missing: number) => {
    const ms = Date.parse(t.start);
    return Number.isNaN(ms) ? missing : ms;
  };
  return [...items].sort((a, b) => ORDER[a.state] - ORDER[b.state] || (a.state === 'final' ? at(b, -Infinity) - at(a, -Infinity) || 0 : at(a, Infinity) - at(b, Infinity) || 0));
}

/** The scores document, reduced to what the Sports tab shows; undefined if it does not look like one. */
export function parseScores(value: unknown): Scores | undefined {
  const v = obj(value);
  if (!v || typeof v.generated !== 'string') return undefined;
  const keep = <T,>(items: unknown[], read: (x: unknown) => T | undefined): T[] => items.map(read).filter((x): x is T => x !== undefined);
  return {
    generated: v.generated,
    nfl: byState(keep(list(v.nfl), game)),
    tennis: byState(keep(list(v.tennis), match)),
    cricket: keep(list(v.cricket), cricket).sort((a, b) => Number(b.live) - Number(a.live)),
    down: (['nfl', 'tennis', 'cricket'] as const).filter((k) => !readable(v[k])),
  };
}

/** Scores older than this are hidden rather than shown as if they were live. */
export function isFresh(generated: string, now: Date): boolean {
  const age = now.getTime() - new Date(generated).getTime();
  return age > -CLOCK_SKEW_MS && age < MAX_AGE_MS;  // NaN and a date far in the future are not fresh
}

const SPORT_OF = new Map<string, Sport>([['nfl', 'nfl'], ['tennis', 'tennis'], ['cricket', 'cricket']]);  // a Map: the key comes from the URL
const LIMITS = { all: { nfl: 6, tennis: 4, cricket: 5 }, one: { nfl: 20, tennis: 20, cricket: 20 } } as const;
const LABELS: Record<Sport, string> = { nfl: 'NFL', tennis: 'Tennis', cricket: 'Cricket' };

export interface ScoreView {
  stale: boolean;
  down: string[];  // names of the shown sports that could not be read
  nfl: Game[];
  tennis: { tournament: string; matches: Match[] }[];  // one group per tournament, in order
  cricket: CricketMatch[];
  total: { nfl: number; tennis: number; cricket: number };  // how many there are in all, for "Show all" under All
}

export interface LiveCard {
  key: string;
  sport: string;  // "NFL", "Cricket", or the tournament for tennis
  rows: { name: string; score: string }[];  // one per side; empty for cricket, whose line is plain text
  line: string;  // the plain cricket line, else ''
  note: string;  // the clock or set, e.g. "Q3 4:12"
  url: string | undefined;
}

/** Everything in play right now, across sports, for the "Live now" strip. Nothing when the scores are stale. */
export function liveNow(scores: Scores | undefined, now: Date): LiveCard[] {
  if (!scores || !isFresh(scores.generated, now)) return [];
  const cards: LiveCard[] = [];
  for (const g of scores.nfl) {
    if (g.state === 'live') cards.push({ key: `nfl-${g.id}`, sport: 'NFL', rows: [g.away, g.home].map((t) => ({ name: t.name, score: t.score === null ? '' : String(t.score) })), line: '', note: g.detail, url: g.url });
  }
  for (const m of scores.tennis) {
    if (m.state === 'live') cards.push({ key: `tennis-${m.id}`, sport: m.tournament || 'Tennis', rows: m.players.map((p) => ({ name: p.name, score: p.sets.join(' ') })), line: '', note: m.detail, url: undefined });
  }
  for (const c of scores.cricket) {
    if (c.live) cards.push({ key: `cricket-${c.id}`, sport: 'Cricket', rows: [], line: c.line, note: '', url: c.url });
  }
  return cards;
}

/** A "Team v Team" line with no score (a number standing on its own, so "U19" does not count) and no star is a fixture that has not started. */
export const cricketUpcoming = (c: CricketMatch): boolean => !c.live && / v /.test(c.line) && !/(^|\s)\d+(\/\d+)?(\s|$)/.test(c.line);

/** What the Sports tab shows for `sub` (every sport under All, or the chosen one); undefined when there is nothing to show
 * at all: no scores file, or a sub-topic that has no scores. */
export function scoresFor(scores: Scores | undefined, sub: string | undefined, now: Date): ScoreView | undefined {
  if (!scores) return undefined;
  const only = sub ? SPORT_OF.get(sub) : undefined;
  if (sub && !only) return undefined;
  const view: ScoreView = { stale: !isFresh(scores.generated, now), down: [], nfl: [], tennis: [], cricket: [], total: { nfl: 0, tennis: 0, cricket: 0 } };
  if (view.stale) return view;
  view.total = { nfl: scores.nfl.length, tennis: scores.tennis.length, cricket: scores.cricket.length };
  const cap = LIMITS[sub ? 'one' : 'all'];
  const shown = (sport: Sport) => !only || only === sport;
  view.down = scores.down.filter(shown).map((k) => LABELS[k]);
  if (shown('nfl')) view.nfl = scores.nfl.slice(0, cap.nfl);
  if (shown('cricket')) view.cricket = scores.cricket.slice(0, cap.cricket);
  if (shown('tennis')) {
    for (const m of scores.tennis.slice(0, cap.tennis)) {
      const group = view.tennis.find((g) => g.tournament === m.tournament);
      if (group) group.matches.push(m);
      else view.tennis.push({ tournament: m.tournament, matches: [m] });
    }
  }
  return view;
}

/** Does the view put anything on the screen (rows or a note)? */
export const hasScores = (v: ScoreView | undefined): boolean => !!v && (v.stale || v.down.length > 0 || v.nfl.length + v.tennis.length + v.cricket.length > 0);
