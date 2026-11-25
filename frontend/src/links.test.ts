import { describe, expect, it } from 'vitest';

import { externalAttrs, isStandalone, linkAttrs } from './links';

describe('linkAttrs', () => {
  it('gives in-app links nothing extra', () => {
    expect(linkAttrs('#/story/a', true)).toEqual({ href: '#/story/a' });
    expect(linkAttrs('#/story/a', false)).toEqual({ href: '#/story/a' });
  });
  it('opens a publisher page in the same window in the installed app', () => {
    expect(linkAttrs('https://example.com/a', true)).toEqual({ href: 'https://example.com/a', rel: 'noopener noreferrer' });
  });
  it('opens a new tab in a normal browser tab', () => {
    expect(linkAttrs('https://example.com/a', false)).toEqual({ href: 'https://example.com/a', target: '_blank', rel: 'noopener noreferrer' });
  });
});

describe('externalAttrs', () => {
  it('is what linkAttrs adds to an external link', () => {
    expect(externalAttrs(true)).toEqual({ rel: 'noopener noreferrer' });
    expect(externalAttrs(false)).toEqual({ target: '_blank', rel: 'noopener noreferrer' });
  });
});

describe('isStandalone', () => {
  it('is true only for the iPhone home-screen app', () => {
    expect(isStandalone({ standalone: true })).toBe(true);
    expect(isStandalone({ standalone: false })).toBe(false);
    expect(isStandalone({})).toBe(false);
    expect(isStandalone(undefined)).toBe(false);
  });
  it('is false when reading the flag throws', () => {
    const nav = { get standalone(): boolean { throw new Error('blocked'); } };
    expect(isStandalone(nav)).toBe(false);
  });
});
