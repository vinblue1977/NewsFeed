export interface Quote {
  symbol: string;
  name: string;
  price: number;
  prevClose: number | null;
  dayOpen: number | null;
  dayHigh: number | null;
  dayLow: number | null;
  history: number[];  // about three months of daily closes, oldest first (empty for an index or when unavailable)
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
    prevClose: num(q.prev_close),
    dayOpen: num(q.day_open),
    dayHigh: num(q.day_high),
    dayLow: num(q.day_low),
    history: Array.isArray(q.history) ? q.history.map(num).filter((n): n is number => n !== null) : [],
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

/** The markets document, reduced to what the screen shows; undefined if it does not look like one. An empty watchlist is valid. */
export function parseMarkets(value: unknown): Markets | undefined {
  const v = value as Record<string, unknown> | null;
  if (!v || typeof v.generated !== 'string') return undefined;
  const indexes = parseList(v.indexes);
  const tickers = parseList(v.tickers);
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

/** "▼ $2.71 (0.36%)": the move in money first, then in percent. Other currencies use their symbol or ISO code. */
export function formatMove(change: number | null, pct: number | null, currency: string): { text: string; dir: 'up' | 'down' | 'flat' } {
  const { text: percent, dir } = formatChange(change, pct);
  if (change === null || dir === 'flat') return { text: percent, dir };
  const arrow = change > 0 ? '▲' : '▼';
  return { text: `${arrow} ${priceLabel(Math.abs(change), currency, false)} (${percent.slice(2)})`, dir };
}

/** "$100.50 – $106.00", or '' when either end is unknown. */
export function dayRange(low: number | null, high: number | null, currency: string): string {
  return low === null || high === null ? '' : `${priceLabel(low, currency, false)} – ${priceLabel(high, currency, false)}`;
}

/** The 3-month change from the first to the last daily close, or undefined with fewer than two points. */
export function historyChange(history: number[]): { change: number; pct: number } | undefined {
  const first = history[0];
  const last = history[history.length - 1];
  if (history.length < 2 || first === undefined || last === undefined || first === 0) return undefined;
  return { change: last - first, pct: ((last - first) / first) * 100 };
}

const MARKET_WORDS = /\b(stocks?|stock market|dow|s&p|nasdaq|wall street|the fed|federal reserve|treasury yields?|bond yields?|bond market|yields?|inflation|earnings|oil prices?|crude|gold prices?|bitcoin|crypto|tariffs?|sensex|nifty|rallies|rally|sell-?off|ipo|interest rates?|rate (?:cut|hike)s?|jobs report|etfs?|commodity prices?|rupee)\b/i;
const COMPANY_SUFFIX = /[,.]?\s+(corporation|corp|incorporated|inc|company|co|holdings|group|ltd|plc|n\.?v|class [a-z]|series \d+)\.?$/i;

const escape = (t: string) => t.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

/** What makes a story about your watchlist: each symbol and each company name (without "Inc." and the like) as a whole word.
 * Compiled once here, not per story. Names match as written (a headline capitalizes them). */
export function watchTerms(quotes: Quote[]): RegExp[] {
  const terms = new Set<string>();
  for (const q of quotes) {
    if (q.symbol.length >= 2) terms.add(q.symbol.replace('^', ''));
    let name = q.name.trim();
    for (let next = name.replace(COMPANY_SUFFIX, ''); next !== name; next = name.replace(COMPANY_SUFFIX, '')) name = next;
    if (name.length >= 4 && name !== q.symbol) terms.add(name);
  }
  return [...terms].map((t) => new RegExp(`(?<![A-Za-z0-9])${escape(t)}(?![A-Za-z0-9])`));
}

/** Is this story market news: from a markets feed, or a headline about markets or something on your watchlist? */
export function isMarketNews(item: { title: string; subtopic?: string }, terms: RegExp[] = []): boolean {
  return item.subtopic === 'markets' || MARKET_WORDS.test(item.title) || terms.some((t) => t.test(item.title));
}
