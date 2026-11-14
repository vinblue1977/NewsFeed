import { describe, expect, it } from 'vitest';
import { MAX_PULL, pullDistance, shouldRefresh, TRIGGER } from './pull';

describe('pull to refresh', () => {
  it('ignores upward and sideways moves', () => {
    expect(pullDistance(-30, 0)).toBe(0);
    expect(pullDistance(0, 0)).toBe(0);
    expect(pullDistance(20, 60)).toBe(0);
  });
  it('follows the finger up to a limit', () => {
    expect(pullDistance(40, 5)).toBe(40);
    expect(pullDistance(1000, 0)).toBe(MAX_PULL);
  });
  it('refreshes only past the trigger distance', () => {
    expect(shouldRefresh(TRIGGER - 1)).toBe(false);
    expect(shouldRefresh(TRIGGER)).toBe(true);
  });
});
