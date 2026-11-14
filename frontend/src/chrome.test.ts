import { describe, expect, it } from 'vitest';

import { nextChrome, progressOf } from './chrome';

const shown = (anchor: number) => ({ hidden: false, anchor });
const hidden = (anchor: number) => ({ hidden: true, anchor });

describe('nextChrome', () => {
  it('hides after scrolling down past the threshold, and shows after scrolling up', () => {
    expect(nextChrome(shown(200), 220, 2000)).toEqual(hidden(220));
    expect(nextChrome(hidden(220), 200, 2000)).toEqual(shown(200));
  });

  it('ignores small moves but lets a slow scroll add up', () => {
    expect(nextChrome(shown(200), 205, 2000)).toEqual(shown(200));  // 5px down: not enough yet
    expect(nextChrome(shown(200), 210, 2000)).toEqual(hidden(210));  // 10px from the anchor
    expect(nextChrome(hidden(300), 303, 2000)).toEqual(hidden(303));  // hidden and still going down: follow along
    expect(nextChrome(hidden(303), 297, 2000)).toEqual(hidden(303));  // a small way back up: stay hidden
    expect(nextChrome(shown(300), 296, 2000)).toEqual(shown(296));  // shown and going up: follow along
  });

  it('always shows near the top and at the end', () => {
    expect(nextChrome(hidden(400), 50, 2000)).toEqual(shown(50));
    expect(nextChrome(hidden(400), 60, 2000)).toEqual(shown(60));
    expect(nextChrome(hidden(1000), 1996, 2000)).toEqual(shown(1996));
  });

  it('ignores positions outside the page (rubber banding)', () => {
    expect(nextChrome(hidden(400), -30, 2000)).toEqual(hidden(400));
    expect(nextChrome(shown(400), 2040, 2000)).toEqual(shown(400));
  });

  it('copes with a page that does not scroll', () => {
    expect(nextChrome(hidden(0), 0, 0)).toEqual(shown(0));
  });
});

describe('progressOf', () => {
  it('is the fraction scrolled, clamped', () => {
    expect(progressOf(500, 2000)).toBe(0.25);
    expect(progressOf(-5, 2000)).toBe(0);
    expect(progressOf(3000, 2000)).toBe(1);
    expect(progressOf(10, 0)).toBe(0);
  });
});
