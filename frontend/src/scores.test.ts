import { describe, expect, it } from 'vitest';
import { byState, cricketUpcoming, hasScores, isFresh, liveNow, parseScores, scoresFor, teamCards, teamMatcher, teamSuggestions } from './scores';

const doc = {
  generated: '2026-11-15T19:00:00+00:00',
  nfl: {
    ok: true,
    entries: [
      { id: 'f', state: 'final', detail: 'Final', start: '2026-11-13T01:15Z', home: { name: 'Giants', score: 21 }, away: { name: 'Commanders', score: 24 }, url: 'https://e.test/f' },
      { id: 'p', state: 'pre', detail: '4:05 PM', start: '2026-11-15T21:05Z', home: { name: 'Raiders', score: null }, away: { name: 'Seahawks', score: null }, url: 'data:text/html,x' },
      { id: 'l', state: 'live', detail: '2nd', start: '2026-11-15T18:00Z', home: { name: 'Falcons', score: 3 }, away: { name: 'Chiefs', score: 7 }, url: null },
      { id: 'bad', state: 'weird', home: { name: 'x' }, away: { name: 'y' } },
    ],
  },
  tennis: {
    ok: true,
    entries: [
      { id: 't', state: 'final', detail: 'Final', start: '2026-11-15T13:25Z', tournament: 'Finals', players: [{ name: 'A', sets: [6, 6, 'x'], winner: true }, { name: 'B', sets: [4, 4], winner: false }] },
      { id: 'one', state: 'pre', detail: '', start: '', tournament: 'Finals', players: [{ name: 'A', sets: [] }] },
    ],
  },
  cricket: { ok: true, entries: [{ id: 'c1', line: 'A v B', live: false, url: 'http://c.test/1' }, { id: 'c2', line: 'C v D 10/1 *', live: true, url: 'file:///etc/passwd' }, { id: '', line: 'no id' }] },
};

describe('parseScores', () => {
  const s = parseScores(doc);
  it('orders games live, then upcoming, then finished, and drops unreadable entries', () => {
    expect(s?.nfl.map((g) => g.id)).toEqual(['l', 'p', 'f']);
    expect(s?.tennis).toHaveLength(1);
    expect(s?.tennis[0]?.players[0]?.sets).toEqual([6, 6]);
    expect(s?.cricket.map((c) => c.id)).toEqual(['c2', 'c1']);
  });
  it('keeps only web links', () => {
    expect(s?.nfl.find((g) => g.id === 'p')?.url).toBeUndefined();
    expect(s?.nfl.find((g) => g.id === 'f')?.url).toBe('https://e.test/f');
    expect(s?.cricket.find((c) => c.id === 'c2')?.url).toBeUndefined();
  });
  it('treats a sport that failed (ok false) as having no entries, and rejects a non-document', () => {
    expect(parseScores({ generated: 'g', nfl: { ok: false, entries: [{ id: 'x' }] } })?.nfl).toEqual([]);
    expect(parseScores(null)).toBeUndefined();
    expect(parseScores({ nfl: {} })).toBeUndefined();
    expect(parseScores([])).toBeUndefined();
  });
  it('sorts finished games latest first', () => {
    const g = (id: string, start: string) => ({ id, state: 'final' as const, start });
    expect(byState([g('a', '2026-11-01'), g('b', '2026-11-05')]).map((x) => x.id)).toEqual(['b', 'a']);
  });
});

describe('isFresh', () => {
  const now = new Date('2026-11-15T19:10:00Z');
  it('is true for recent scores and false for old, future or unreadable ones', () => {
    expect(isFresh('2026-11-15T19:00:00Z', now)).toBe(true);
    expect(isFresh('2026-11-15T18:00:00Z', now)).toBe(false);
    expect(isFresh('2026-11-16T19:00:00Z', now)).toBe(false);
    expect(isFresh('nope', now)).toBe(false);
  });
});

describe('scoresFor', () => {
  const now = new Date('2026-11-15T19:10:00Z');
  const scores = parseScores(doc);
  it('shows every sport under All and only the chosen one under a sport chip', () => {
    const all = scoresFor(scores, undefined, now);
    expect([all?.nfl.length, all?.tennis.length, all?.cricket.length]).toEqual([3, 1, 2]);
    const nfl = scoresFor(scores, 'nfl', now);
    expect([nfl?.nfl.length, nfl?.tennis.length, nfl?.cricket.length]).toEqual([3, 0, 0]);
  });
  it('shows nothing for a sub-topic without scores, including names that only an object would know', () => {
    for (const sub of ['soccer', 'constructor', 'toString', '__proto__']) expect(scoresFor(scores, sub, now)).toBeUndefined();
    expect(scoresFor(undefined, undefined, now)).toBeUndefined();
  });
  it('groups tennis by tournament and keeps the order', () => {
    const two = parseScores({ generated: doc.generated, tennis: { ok: true, entries: [
      { id: '1', state: 'live', start: '2026-11-15T10:00Z', tournament: 'A', players: [{ name: 'p', sets: [] }, { name: 'q', sets: [] }] },
      { id: '2', state: 'live', start: '2026-11-15T11:00Z', tournament: 'B', players: [{ name: 'p', sets: [] }, { name: 'q', sets: [] }] },
      { id: '3', state: 'live', start: '2026-11-15T12:00Z', tournament: 'A', players: [{ name: 'p', sets: [] }, { name: 'q', sets: [] }] },
    ] } });
    expect(scoresFor(two, 'tennis', now)?.tennis.map((g) => [g.tournament, g.matches.length])).toEqual([['A', 2], ['B', 1]]);
  });
  it('says so when scores are out of date or a sport could not be read', () => {
    const old = scoresFor(scores, undefined, new Date('2026-11-15T21:00:00Z'));
    expect(old?.stale).toBe(true);
    expect(hasScores(old)).toBe(true);
    const down = scoresFor(parseScores({ generated: doc.generated, nfl: { ok: false, entries: [] }, tennis: { ok: true, entries: [] }, cricket: { ok: true, entries: [] } }), undefined, now);
    expect(down?.down).toEqual(['NFL']);
    expect(hasScores(down)).toBe(true);
    expect(hasScores(scoresFor(parseScores({ generated: doc.generated, nfl: { ok: true, entries: [] }, tennis: { ok: true, entries: [] }, cricket: { ok: true, entries: [] } }), undefined, now))).toBe(false);
    expect(hasScores(undefined)).toBe(false);
  });
});

describe('long ids and lines', () => {
  it('keeps a long cricket id and line whole, so two matches never share a key or lose the score', () => {
    const base = `http://www.cricinfo.com/ci/engine/series/${'x'.repeat(90)}/match/`;
    const line = 'Team A 245/6 (50 ov) v Team B 120/3 (20.1 ov) *';
    const s = parseScores({ generated: 'g', cricket: { ok: true, entries: [{ id: `${base}1.html`, line, live: true }, { id: `${base}2.html`, line, live: true }] } });
    expect(new Set(s?.cricket.map((c) => c.id)).size).toBe(2);
    expect(s?.cricket[0]?.line).toBe(line);
  });
  it('orders by real dates, not strings: an offset or seconds do not confuse it, and a missing start is last', () => {
    const g = (id: string, start: string) => ({ id, state: 'pre' as const, start });
    expect(byState([g('none', ''), g('late', '2026-11-15T21:05:30Z'), g('early', '2026-11-15T20:00+00:00')]).map((x) => x.id)).toEqual(['early', 'late', 'none']);
  });
});

describe('liveNow and cricketUpcoming', () => {
  const now = new Date('2026-11-15T19:10:00Z');
  it('lists only matches in play, and nothing when the scores are stale', () => {
    const cards = liveNow(parseScores(doc), now);
    expect(cards.length).toBeGreaterThan(0);
    expect(cards.every((c) => c.rows.length === 2 || c.line !== '')).toBe(true);
    expect(liveNow(parseScores(doc), new Date('2027-01-01T00:00:00Z'))).toEqual([]);
    expect(liveNow(undefined, now)).toEqual([]);
  });
  it('treats a cricket line with no score and no star as upcoming', () => {
    expect(cricketUpcoming({ id: 'a', line: 'New South Wales v South Australia', live: false, url: undefined })).toBe(true);
    expect(cricketUpcoming({ id: 'b', line: 'South Africa v Bangladesh 327/6 *', live: true, url: undefined })).toBe(false);
    expect(cricketUpcoming({ id: 'u', line: 'India U19 v Pakistan U19', live: false, url: undefined })).toBe(true);
    expect(cricketUpcoming({ id: 'c', line: 'India 250/4 v Australia 180', live: false, url: undefined })).toBe(false);
  });
});

describe('my teams', () => {
  const now = new Date('2026-11-15T19:10:00Z');
  const scores = parseScores(doc);
  it('matches whole words in any case and nothing when nothing is followed', () => {
    const has = teamMatcher(['India', 'Bears']);
    expect(has?.('india beat Indiana')).toBe(true);
    expect(has?.('Indiana Hoosiers')).toBe(false);
    expect(has?.('Chicago BEARS')).toBe(true);
    expect(teamMatcher([])).toBeNull();
    expect(teamMatcher(['  '])).toBeNull();
    expect(teamMatcher(['C++ (x)'])?.('C++ (x) wins')).toBe(true);  // names are text, not patterns
  });
  it('lists the followed games, live first, then upcoming, then finished', () => {
    const cards = teamCards(scores, ['Falcons', 'Raiders', 'Giants'], now);
    expect(cards.map((c) => c.state)).toEqual(['live', 'pre', 'final']);
    expect(cards[0]?.rows.map((r) => r.name)).toEqual(['Chiefs', 'Falcons']);
  });
  it('shows nothing for no followed names, a name nobody plays, or stale scores', () => {
    expect(teamCards(scores, [], now)).toEqual([]);
    expect(teamCards(scores, ['Nobody'], now)).toEqual([]);
    expect(teamCards(scores, ['Falcons'], new Date('2027-01-01T00:00:00Z'))).toEqual([]);
    expect(teamCards(undefined, ['Falcons'], now)).toEqual([]);
  });
  it('suggests nicknames, surnames and cricket sides without repeats', () => {
    const got = teamSuggestions(scores);
    expect(got).toContain('Falcons');
    expect(new Set(got.map((g) => g.toLowerCase())).size).toBe(got.length);
    expect(teamSuggestions(undefined)).toEqual([]);
  });
});
