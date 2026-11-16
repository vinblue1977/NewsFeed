import { describe, expect, it } from 'vitest';

import { parseSchedule, teamSchedules } from './schedule';

const now = new Date('2026-11-16T15:00:00Z');  // a Monday, week 10 is over except tonight
const t = (name: string) => ({ name, abbr: name.slice(0, 3).toUpperCase() });
const game = (id: string, week: number, start: string, home: string, away: string) => ({ id, week, start, home: t(home), away: t(away) });

const doc = {
  generated: '2026-11-16T12:00:00Z',
  games: [
    game('w10a', 10, '2026-11-15T18:00Z', 'Chicago Bears', 'Detroit Lions'),  // already played
    game('w10b', 10, '2026-11-17T01:15Z', 'Green Bay Packers', 'Minnesota Vikings'),  // tonight
    game('w11a', 11, '2026-11-22T18:00Z', 'Minnesota Vikings', 'Chicago Bears'),
    game('w11b', 11, '2026-11-22T21:25Z', 'Detroit Lions', 'Green Bay Packers'),
    game('w12a', 12, '2026-11-26T17:30Z', 'Detroit Lions', 'Chicago Bears'),
    game('w13b', 13, '2026-12-06T18:00Z', 'Green Bay Packers', 'Minnesota Vikings'),
    game('w13a', 13, '2026-12-06T21:25Z', 'Chicago Bears', 'Detroit Lions'),
    game('w14', 14, '2026-12-13T18:00Z', 'Minnesota Vikings', 'Detroit Lions'),
  ],
};

describe('parseSchedule', () => {
  it('keeps valid games and drops what is not usable', () => {
    const bad = [{ id: 'x' }, null, game('', 1, '2026-11-22T18:00Z', 'A', 'B'), game('y', 0, '2026-11-22T18:00Z', 'A', 'B'), game('z', 5, 'not a date', 'A', 'B'), { ...game('q', 5, '2026-11-22T18:00Z', 'A', 'B'), home: { name: 5 } }];
    const got = parseSchedule({ generated: doc.generated, games: [...doc.games, ...bad] }, now);
    expect(got?.games.map((g) => g.id)).toEqual(doc.games.map((g) => g.id));
  });

  it('shows nothing for a missing, malformed, oversized or stale file', () => {
    expect(parseSchedule(null, now)).toBeUndefined();
    expect(parseSchedule({ generated: 5, games: [] }, now)).toBeUndefined();
    expect(parseSchedule({ generated: doc.generated, games: 'x' }, now)).toBeUndefined();
    expect(parseSchedule({ generated: '2026-11-10T00:00:00Z', games: doc.games }, now)).toBeUndefined();  // six days old
    expect(parseSchedule({ generated: 'not a date', games: doc.games }, now)).toBeUndefined();
    expect(parseSchedule({ generated: '2026-11-19T12:00:00Z', games: doc.games }, now)).toBeUndefined();  // three days ahead: a bad clock
    expect(parseSchedule({ generated: '2026-11-16T15:20:00Z', games: doc.games }, now)?.games).toHaveLength(doc.games.length);  // a little skew is fine
    expect(parseSchedule({ generated: doc.generated, games: Array.from({ length: 401 }, () => doc.games[0]) }, now)).toBeUndefined();
  });
});

describe('teamSchedules', () => {
  const schedule = parseSchedule(doc, now);

  it('lists the games still to start, soonest first, home or away', () => {
    const [bears] = teamSchedules(schedule, ['Bears'], now);
    expect(bears?.team).toBe('Chicago Bears');
    const rows = bears?.rows.filter((r) => r.kind === 'game').map((r) => (r.kind === 'game' ? [r.week, r.opponent, r.atHome] : []));
    expect(rows).toEqual([[11, 'Minnesota Vikings', false], [12, 'Detroit Lions', false], [13, 'Detroit Lions', true]]);  // the finished week-10 game is not listed
  });

  it('marks a week the team has no game at all as a bye, only for weeks still to be played', () => {
    const [bears] = teamSchedules(schedule, ['Chicago Bears'], now);
    expect(bears?.rows.map((r) => [r.kind, r.week])).toEqual([['game', 11], ['game', 12], ['game', 13], ['bye', 14]]);
    const [packers] = teamSchedules(schedule, ['Packers'], now);
    expect(packers?.rows.map((r) => [r.kind, r.week])).toEqual([['game', 10], ['game', 11], ['bye', 12], ['game', 13], ['bye', 14]]);  // tonight's game is still to come
  });

  it('keeps the order the names were followed, lists a team once, and matches any team with the name as a word', () => {
    const got = teamSchedules(schedule, ['Lions', 'Bears', 'Detroit'], now);
    expect(got.map((s) => s.team)).toEqual(['Detroit Lions', 'Chicago Bears']);  // "Detroit" matches the Lions again: not repeated
    expect(teamSchedules(schedule, ['Bear'], now)).toEqual([]);  // not a whole word
    expect(teamSchedules(schedule, ['New York'], now)).toEqual([]);  // no such team in this file
  });

  it('shows no bye for a week the file may be missing a game from, and reads partial_weeks safely', () => {
    const partial = parseSchedule({ ...doc, partial_weeks: [14, 'x', 1.5, null] }, now);
    expect(partial?.partialWeeks).toEqual([14]);
    const [bears] = teamSchedules(partial, ['Bears'], now);
    expect(bears?.rows.map((r) => [r.kind, r.week])).toEqual([['game', 11], ['game', 12], ['game', 13]]);  // week 14 is unsure: no bye
    expect(parseSchedule({ ...doc, partial_weeks: 'nope' }, now)?.partialWeeks).toEqual([]);
  });

  it('shows nothing for no followed names, no file or a finished season', () => {
    expect(teamSchedules(schedule, [], now)).toEqual([]);
    expect(teamSchedules(undefined, ['Lions'], now)).toEqual([]);
    expect(teamSchedules(schedule, ['Lions'], new Date('2027-02-01T00:00:00Z'))).toEqual([]);
  });
});
