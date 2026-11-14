export interface Quote {
  symbol: string;
  name: string;
  price: number;
  change: number | null;
  changePct: number | null;
  currency: string;
  open: boolean;
  lastTrade: string | null;
  series: number[];
}

export interface Markets {
  generated: string;
  indexes: Quote[];
  tickers: Quote[];
  missing: number;  // symbols the ingest could not read
}

const MAX_AGE_MS = 60 * 60 * 1000;
const CLOCK_SKEW_MS = 5 * 60 * 1000;

const num = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) ? v : null);

function parseQuote(value: unknown): Quote | 'missing' | undefined {
  const q = value as Record<string, unknown> | null;
  if (!q || typeof q.symbol !== 'string') return undefined;
  const price = num(q.price);
  if (q.ok !== true || price === null) return 'missing';
  return {
    symbol: q.symbol,
    name: typeof q.name === 'string' && q.name ? q.name : q.symbol,
    price,
    change: num(q.change),
    changePct: num(q.change_pct),
    currency: typeof q.currency === 'string' ? q.currency : '',
    open: q.open === true,
    lastTrade: typeof q.last_trade === 'string' ? q.last_trade : null,
    series: Array.isArray(q.series) ? q.series.map(num).filter((n): n is number => n !== null) : [],
  };
}

function parseList(value: unknown): { quotes: Quote[]; missing: number } {
  const quotes: Quote[] = [];
  let missing = 0;
  for (const raw of Array.isArray(value) ? value : []) {
    const q = parseQuote(raw);
    if (q === undefined || q === 'missing') missing += 1;  // an entry that is not even a quote counts as unavailable too
    else quotes.push(q);
  }
  return { quotes, missing };
}

/** The markets document, reduced to what the screen shows; undefined if it does not look like one or has no readable quote. */
export function parseMarkets(value: unknown): Markets | undefined {
  const v = value as Record<string, unknown> | null;
  if (!v || typeof v.generated !== 'string') return undefined;
  const indexes = parseList(v.indexes);
  const tickers = parseList(v.tickers);
  if (indexes.quotes.length + tickers.quotes.length === 0) return undefined;
  return { generated: v.generated, indexes: indexes.quotes, tickers: tickers.quotes, missing: indexes.missing + tickers.missing };
}

/** Prices older than this are flagged rather than shown as if they were current. */
export function isFresh(generated: string, now: Date): boolean {
  const age = now.getTime() - new Date(generated).getTime();
  return age > -CLOCK_SKEW_MS && age < MAX_AGE_MS;  // NaN (an unreadable date) and a date far in the future are not fresh
}

const CURRENCY: Record<string, string> = { USD: '$', INR: '₹', EUR: '€', GBP: '£', JPY: '¥' };

export function formatPrice(price: number): string {
  return price.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

/** "▼ 0.40%" / "▲ 0.10%" (an arrow as well as a colour, so the direction does not rely on colour alone). */
export function formatChange(change: number | null, pct: number | null): { text: string; dir: 'up' | 'down' | 'flat' } {
  if (change === null || pct === null) return { text: '–', dir: 'flat' };
  if (change === 0 || Math.abs(pct) < 0.005) return { text: '0.00%', dir: 'flat' };  // a move that rounds to zero is flat, not up or down
  return { text: `${change > 0 ? '▲' : '▼'} ${Math.abs(pct).toFixed(2)}%`, dir: change > 0 ? 'up' : 'down' };
}

/** "$" for a known currency, otherwise the ISO code ("CAD 12.30"); nothing for an index, whose level is in points. */
export const priceLabel = (price: number, currency: string, index: boolean): string => {
  const amount = formatPrice(price);
  if (index || !currency) return amount;
  return CURRENCY[currency] ? `${CURRENCY[currency]}${amount}` : `${currency} ${amount}`;
};

/** The points of a sparkline in a width x height box, or '' when fewer than two values. */
export function sparkline(series: number[], width = 100, height = 28): string {
  if (series.length < 2) return '';
  const min = Math.min(...series);
  const span = Math.max(...series) - min || 1;
  return series
    .map((v, i) => `${((i / (series.length - 1)) * width).toFixed(1)},${(height - ((v - min) / span) * (height - 2) - 1).toFixed(1)}`)
    .join(' ');
}
