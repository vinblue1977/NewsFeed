/** The Linux kernel's current releases (data/kernel.json): three rows for the Technology list. */
export interface KernelRow {
  branch: string;
  version: string;
  released: string;  // yyyy-mm-dd
}

export interface Kernel {
  generated: string;
  rows: KernelRow[];
}

const VERSION = /^[0-9][0-9A-Za-z.-]{0,23}$/;
const DATE = /^\d{4}-\d{2}-\d{2}$/;
const BRANCHES = ['Mainline', 'Stable', 'Longterm'];

/** The kernel document, or undefined if it does not look like one. Rows are kept only when well formed, in the order of BRANCHES. */
export function parseKernel(value: unknown): Kernel | undefined {
  const v = value as { generated?: unknown; rows?: unknown } | null;
  if (!v || typeof v.generated !== 'string' || !Array.isArray(v.rows)) return undefined;
  const rows = BRANCHES.flatMap((branch) => {
    const r = (v.rows as unknown[]).find((x) => (x as { branch?: unknown } | null)?.branch === branch) as Record<string, unknown> | undefined;
    return r && typeof r.version === 'string' && VERSION.test(r.version) && typeof r.released === 'string' && DATE.test(r.released)
      ? [{ branch, version: r.version, released: r.released }]
      : [];
  });
  return rows.length > 0 ? { generated: v.generated, rows } : undefined;
}

const MAX_AGE_MS = 7 * 24 * 3600_000;
const CLOCK_SKEW_MS = 5 * 60_000;

/** A table older than a week is hidden (the ingest keeps the last file when kernel.org cannot be read), like a stale forecast. */
export function kernelFresh(generated: string, now: Date): boolean {
  const age = now.getTime() - new Date(generated).getTime();
  return age > -CLOCK_SKEW_MS && age < MAX_AGE_MS;  // an unreadable date is not fresh
}

/** The table's header: "Linux kernel", plus the Stable version when asked (shown while the table is folded, so the key fact stays visible). */
export function kernelTitle(kernel: Kernel, withStable: boolean): string {
  const stable = kernel.rows.find((r) => r.branch === 'Stable');
  return withStable && stable ? `Linux kernel · ${stable.version}` : 'Linux kernel';
}
