/** The NFL schedule from data/schedule.json (public: the same for everyone). The followed teams stay on the device, so this
 * file is filtered here. Every field is checked: the file is not trusted, and a bad entry is dropped. */
import { teamMatcher } from './scores';

export interface SchedTeam {
  name: string;
  abbr: string;
}

export interface SchedGame {
  id: string;
  week: number;
  start: string;  // an ISO date and time
  home: SchedTeam;
  away: SchedTeam;
}

export interface Schedule {
  generated: string;
  games: SchedGame[];
  partialWeeks: number[];  // weeks that may be missing a game: no bye is shown for them
}

const MAX_AGE_MS = 3 * 24 * 3600_000;  // an older file means the ingest has stopped updating it: show nothing
const CLOCK_SKEW_MS = 3600_000;  // a file stamped further ahead than this is not believed
const MAX_GAMES = 400;  // a season has about 270; a bigger file is not a schedule
const MAX_TEXT = 60;

const text = (v: unknown): string => (typeof v === 'string' && v.length > 0 && v.length <= MAX_TEXT ? v : '');

function team(v: unknown): SchedTeam | undefined {
  const o = v as Record<string, unknown> | null;
  const name = text(o?.name);
  return o && name ? { name, abbr: typeof o.abbr === 'string' ? o.abbr.slice(0, 5) : '' } : undefined;
}

export function parseSchedule(value: unknown, now: Date): Schedule | undefined {
  const v = value as Record<string, unknown> | null;
  if (!v || typeof v.generated !== 'string' || !Array.isArray(v.games) || v.games.length > MAX_GAMES) return undefined;
  const age = now.getTime() - new Date(v.generated).getTime();
  if (!(age < MAX_AGE_MS && age > -CLOCK_SKEW_MS)) return undefined;  // also false for NaN
  const games: SchedGame[] = [];
  for (const raw of v.games as unknown[]) {
    const o = raw as Record<string, unknown> | null;
    const home = team(o?.home);
    const away = team(o?.away);
    const id = text(o?.id);
    const week = o?.week;
    const start = typeof o?.start === 'string' ? o.start : '';
    if (o && id && home && away && typeof week === 'number' && Number.isInteger(week) && week >= 1 && week <= 25 && !Number.isNaN(Date.parse(start))) {
      games.push({ id, week, start, home, away });
    }
  }
  const partialWeeks = Array.isArray(v.partial_weeks) ? v.partial_weeks.filter((w): w is number => Number.isInteger(w)) : [];
  return { generated: v.generated, games, partialWeeks };
}

export type SchedRow =
  | { kind: 'game'; game: SchedGame; atHome: boolean; opponent: string; week: number }
  | { kind: 'bye'; week: number };

export interface TeamSchedule {
  team: string;
  rows: SchedRow[];  // the games still to start and the weeks off, in order
}

/** The upcoming games and bye weeks of each followed team, in the order the names were followed. A name matches any team whose
 * name has it as a whole word ("Bears" or "Chicago Bears"); a team is listed once. A bye is a week still to be played in which
 * the team has no game at all, and the file is complete for that week. Teams with nothing to show are left out. */
export function teamSchedules(schedule: Schedule | undefined, terms: string[], now: Date): TeamSchedule[] {
  if (!schedule) return [];
  const t = now.getTime();
  const names = [...new Set(schedule.games.flatMap((g) => [g.home.name, g.away.name]))];
  const openWeeks = new Set(schedule.games.filter((g) => Date.parse(g.start) > t).map((g) => g.week));
  const unsure = new Set(schedule.partialWeeks);  // a game may be missing from these weeks, so a team without one is not on a bye
  const seen = new Set<string>();
  const out: TeamSchedule[] = [];
  for (const term of terms) {
    const has = teamMatcher([term]);
    if (!has) continue;
    for (const name of names.filter((n) => has(n) && !seen.has(n))) {
      seen.add(name);
      const mine = schedule.games.filter((g) => g.home.name === name || g.away.name === name);
      const played = new Set(mine.map((g) => g.week));
      const rows: SchedRow[] = [
        ...mine
          .filter((g) => Date.parse(g.start) > t)
          .map((g): SchedRow => ({ kind: 'game', game: g, atHome: g.home.name === name, opponent: g.home.name === name ? g.away.name : g.home.name, week: g.week })),
        ...[...openWeeks].filter((w) => !played.has(w) && !unsure.has(w)).map((w): SchedRow => ({ kind: 'bye', week: w })),
      ].sort((a, b) => a.week - b.week || (a.kind === 'game' && b.kind === 'game' ? Date.parse(a.game.start) - Date.parse(b.game.start) : 0));
      if (rows.length > 0) out.push({ team: name, rows });
    }
  }
  return out;
}
