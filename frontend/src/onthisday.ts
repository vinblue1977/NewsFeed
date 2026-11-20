/** The "on this day" facts (data/onthisday.json) for the end of the briefing card: one per day, for the days around the
 *  ingest's UTC day, so every reader's own calendar day is among them. */
export interface Fact {
  year: number;
  text: string;
}

export interface OnThisDay {
  days: Record<string, Fact>;  // yyyy-mm-dd -> that day's fact
}

const DATE = /^\d{4}-\d{2}-\d{2}$/;
const MAX_TEXT = 200;  // the ingest keeps it near 160; anything much longer is not ours

/** The document, keeping only well-formed days; undefined if it does not look like one or no day is usable. */
export function parseOnThisDay(value: unknown): OnThisDay | undefined {
  const days = (value as { days?: unknown } | null)?.days;
  if (!days || typeof days !== 'object' || Array.isArray(days)) return undefined;
  const out: Record<string, Fact> = {};
  for (const [date, f] of Object.entries(days)) {
    const { year, text } = (f ?? {}) as { year?: unknown; text?: unknown };
    if (!DATE.test(date) || typeof year !== 'number' || !Number.isInteger(year) || year < 1 || year > 9999) continue;
    if (typeof text !== 'string' || text.trim() === '' || text.length > MAX_TEXT) continue;
    out[date] = { year, text: text.trim() };
  }
  return Object.keys(out).length > 0 ? { days: out } : undefined;
}

/** The fact for `day` (the local day, as briefing.ts's dayKey gives it), or undefined: an old file must not pass as today's. */
export function factFor(doc: OnThisDay | undefined, day: string): Fact | undefined {
  return doc && Object.hasOwn(doc.days, day) ? doc.days[day] : undefined;
}
