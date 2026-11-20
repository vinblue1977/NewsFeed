import { describe, expect, it } from 'vitest';
import { type Kernel, kernelFresh, kernelTitle, parseKernel } from './kernel';

const rows = [
  { branch: 'Longterm', version: '6.18.64', released: '2026-11-17' },
  { branch: 'Mainline', version: '7.4-rc3', released: '2026-11-15' },
  { branch: 'Stable', version: '7.3.5', released: '2026-11-17' },
];

describe('parseKernel', () => {
  it('keeps the three rows in Mainline, Stable, Longterm order', () => {
    expect(parseKernel({ generated: 'g', rows })?.rows.map((r) => [r.branch, r.version])).toEqual([['Mainline', '7.4-rc3'], ['Stable', '7.3.5'], ['Longterm', '6.18.64']]);
  });

  it('drops a malformed row and keeps the rest', () => {
    const bad = [{ branch: 'Mainline', version: '<b>x</b>', released: '2026-11-15' }, { branch: 'Stable', version: '7.3.5', released: 'soon' }, rows[0]];
    expect(parseKernel({ generated: 'g', rows: bad })?.rows).toEqual([rows[0]]);
  });

  it('gives undefined for anything that is not a kernel document, or has no usable row', () => {
    for (const v of [null, 'x', {}, { generated: 'g' }, { generated: 1, rows }, { generated: 'g', rows: 'x' }, { generated: 'g', rows: [] }, { generated: 'g', rows: [null, 5] }]) {
      expect(parseKernel(v)).toBeUndefined();
    }
  });
});

describe('kernelFresh', () => {
  const now = new Date('2026-11-20T12:00:00Z');
  it('shows a table up to a week old and hides an older, future or unreadable one', () => {
    expect(kernelFresh('2026-11-20T11:00:00Z', now)).toBe(true);
    expect(kernelFresh('2026-11-14T13:00:00Z', now)).toBe(true);
    expect(kernelFresh('2026-11-13T12:00:00Z', now)).toBe(false);
    expect(kernelFresh('2026-11-21T12:00:00Z', now)).toBe(false);
    expect(kernelFresh('nope', now)).toBe(false);
  });
});

describe('kernelTitle', () => {
  const kernel: Kernel = { generated: 'g', rows };
  it('adds the Stable version only when asked', () => {
    expect(kernelTitle(kernel, true)).toBe('Linux kernel · 7.3.5');
    expect(kernelTitle(kernel, false)).toBe('Linux kernel');
  });

  it('finds the Stable row in what parseKernel really returns (the two must agree on the branch name)', () => {
    const parsed = parseKernel({ generated: 'g', rows });
    expect(parsed && kernelTitle(parsed, true)).toBe('Linux kernel · 7.3.5');
  });

  it('has no version to add when there is no Stable row', () => {
    expect(kernelTitle({ generated: 'g', rows: [{ branch: 'Mainline', version: '7.4-rc3', released: '2026-11-15' }] }, true)).toBe('Linux kernel');
  });
});
