import { describe, expect, it } from 'vitest';

import { greeting } from './App';

describe('greeting', () => {
  it('greets by name', () => {
    expect(greeting('News')).toBe('Hello, News');
  });
});
