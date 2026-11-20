import { describe, expect, it } from 'vitest';
import type { Story } from './feed';
import { cleanFollows, FOLLOW_PER_GROUP, followGroups, followLabel, keywordKey, keywordWords, MAX_FOLLOWS, parseFollow, toggleFollow, topicKey } from './follow';
import type { Topic } from './types';

const mk = (id: string, title: string, o: { topic?: Topic; sub?: string; summary?: string; at?: string } = {}): Story => ({
  item: { id, title, url: `https://x/${id}`, summary: o.summary ?? '', published: o.at ?? '2026-11-20T10:00:00Z', source: 'S', topic: o.topic ?? 'us', subtopic: o.sub },
  cluster: undefined,
  sources: 1,
});

describe('follow keys', () => {
  it('reads topic and keyword follows and rejects the rest', () => {
    expect(parseFollow('topic:gadgets')).toEqual({ kind: 'topic', id: 'gadgets' });
    expect(parseFollow('kw:US election, midterms')).toEqual({ kind: 'keyword', words: ['US election', 'midterms'] });
    for (const bad of ['topic:', 'topic:Bad Id', 'kw:', 'kw: , ,', 'nope', '']) expect(parseFollow(bad)).toBeUndefined();
  });

  it('cleans typed keywords: trimmed, spaced once, no repeats, no one-letter words', () => {
    expect(keywordWords('  US   election , us ELECTION, a, midterms,, ')).toEqual(['US election', 'midterms']);
    expect(keywordWords('x'.repeat(41))).toEqual([]);
    expect(keywordWords(Array.from({ length: 12 }, (_, i) => `word${i}`).join(','))).toHaveLength(8);
    expect(keywordKey('US election, midterms')).toBe('kw:US election,midterms');
    expect(keywordKey(' , ')).toBeUndefined();
  });

  it('toggles a follow on and off, and stops adding at the limit', () => {
    expect(toggleFollow([], 'topic:nfl')).toEqual(['topic:nfl']);
    expect(toggleFollow(['topic:nfl'], 'topic:nfl')).toEqual([]);
    const full = Array.from({ length: MAX_FOLLOWS }, (_, i) => `kw:word${i}`);
    expect(toggleFollow(full, 'kw:extra')).toEqual(full);
    expect(toggleFollow(full, 'kw:word0')).toHaveLength(MAX_FOLLOWS - 1);
  });

  it('cleans a stored list', () => {
    expect(cleanFollows(['topic:nfl', 'topic:nfl', 'bad', 'kw:ab'])).toEqual(['topic:nfl', 'kw:ab']);
    expect(cleanFollows(['kw:US election', 'kw:us ELECTION', 'kw: US   election ,x'])).toEqual(['kw:US election']);  // one follow, whatever the case or spacing
  });

  it('labels a topic by its title and a keyword by its first word', () => {
    expect(followLabel({ kind: 'topic', id: 'gadgets' })).toBe('Technology');
    expect(followLabel({ kind: 'keyword', words: ['US election', 'midterms'] })).toBe('US election');
  });
});

describe('followGroups', () => {
  const pool = [
    mk('t1', 'New phone leak', { topic: 'tech', sub: 'gadgets', at: '2026-11-20T12:00:00Z' }),
    mk('e1', 'US election: polls open in key states', { at: '2026-11-20T11:00:00Z' }),
    mk('e2', 'Why the selection process matters', { at: '2026-11-20T10:30:00Z' }),
    mk('e3', 'Voters weigh in', { summary: 'The midterms are close', topic: 'world', at: '2026-11-20T10:00:00Z' }),
    mk('w1', 'EU talks end', { topic: 'world', at: '2026-11-20T09:00:00Z' }),
    mk('n1', 'NFL week 12', { topic: 'sports', sub: 'nfl', at: '2026-11-20T08:00:00Z' }),
  ];

  it('groups a followed topic by its sub-topic, with the route of its list', () => {
    const [g] = followGroups([topicKey('gadgets'), topicKey('nfl'), topicKey('world')], pool);
    expect(g).toMatchObject({ label: 'Technology', total: 1, route: '#/discovery/gadgets' });
    const all = followGroups([topicKey('nfl'), topicKey('world')], pool);
    expect(all.map((x) => [x.label, x.route])).toEqual([['NFL', '#/sports/nfl'], ['World News', '#/discovery/world']]);
  });

  it('matches keywords at the start of a word, in the headline or summary, any case, and has no list route', () => {
    const [g] = followGroups(['kw:us ELECTION,midterms'], pool);
    expect(g?.stories.map((s) => s.item.id)).toEqual(['e1', 'e3']);  // not "selection"
    expect(g).toMatchObject({ label: 'us ELECTION', total: 2, route: undefined });
  });

  it('does not treat regex characters in a keyword as a pattern', () => {
    expect(followGroups(['kw:.*'], pool)).toEqual([]);
    expect(followGroups(['kw:(a|b'], pool)).toEqual([]);
  });

  it('shows the newest FOLLOW_PER_GROUP and counts them all', () => {
    const many = Array.from({ length: 9 }, (_, i) => mk(`m${i}`, `Quake update ${i}`, { at: `2026-11-20T0${i}:00:00Z` })).reverse();
    const [g] = followGroups(['kw:quake'], many);
    expect(g?.stories).toHaveLength(FOLLOW_PER_GROUP);
    expect(g?.total).toBe(9);
    expect(g?.stories[0]?.item.id).toBe('m8');
  });

  it('never shows a story twice, nor one in skip, and leaves out a follow with nothing new', () => {
    const groups = followGroups(['kw:election', 'kw:polls', topicKey('gadgets')], pool, new Set(['t1']));
    expect(groups.map((g) => g.label)).toEqual(['election']);  // polls' only match was shown above; Technology's only story is skipped
  });

  it('skips unreadable keys', () => {
    expect(followGroups(['bad', 'topic:'], pool)).toEqual([]);
  });
});
