import { describe, expect, it } from 'vitest';

import { groupBlocks, parseArticles, readingMinutes } from './article';

describe('parseArticles', () => {
  it('keeps well-formed blocks and drops the rest', () => {
    const got = parseArticles({
      articles: {
        a: [{ t: 'p', x: 'One' }, { t: 'img', x: 'no' }, { t: 'h', x: '  ' }, { t: 'li', x: 5 }, null, { t: 'q', x: 'Quote' }],
        b: [{ t: 'x', x: 'nothing valid' }],
        c: 'not a list',
      },
    });
    expect(got).toEqual({ a: [{ t: 'p', x: 'One' }, { t: 'q', x: 'Quote' }] });
  });

  it('does not let ids like constructor match inherited properties', () => {
    const got = parseArticles({ articles: { a: [{ t: 'p', x: 'One' }] } });
    expect(got?.['constructor']).toBeUndefined();
    expect(got?.['toString']).toBeUndefined();
  });

  it('rejects anything that is not an articles document', () => {
    expect(parseArticles(null)).toBeUndefined();
    expect(parseArticles({})).toBeUndefined();
    expect(parseArticles({ articles: [] })).toBeUndefined();
    expect(parseArticles({ articles: null })).toBeUndefined();
    expect(parseArticles({ articles: {} })).toEqual({});
  });
});

describe('reading helpers', () => {
  it('estimates minutes, at least one', () => {
    expect(readingMinutes([{ t: 'p', x: 'few words' }])).toBe(1);
    expect(readingMinutes([{ t: 'p', x: Array.from({ length: 660 }, () => 'w').join(' ') }])).toBe(3);
  });

  it('groups consecutive list items into one list', () => {
    expect(
      groupBlocks([
        { t: 'h', x: 'Head' },
        { t: 'li', x: 'a' },
        { t: 'li', x: 'b' },
        { t: 'p', x: 'Para' },
        { t: 'li', x: 'c' },
        { t: 'q', x: 'Quote' },
      ]),
    ).toEqual([
      { kind: 'h', text: 'Head' },
      { kind: 'list', items: ['a', 'b'] },
      { kind: 'p', text: 'Para' },
      { kind: 'list', items: ['c'] },
      { kind: 'q', text: 'Quote' },
    ]);
  });
});
