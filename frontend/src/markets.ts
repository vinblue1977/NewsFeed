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
  const { text, dir } = formatChange(change, pct);
  if (change === null || pct === null || dir === 'flat') return { text, dir };
  const arrow = change > 0 ? '▲' : '▼';
  const percent = `${Math.abs(pct).toFixed(2)}%`;
  // a move under half a cent would read "$0.00" beside an arrow: show the percent alone
  if (Math.abs(change) < 0.005) return { text: `${arrow} ${percent}`, dir };
  return { text: `${arrow} ${priceLabel(Math.abs(change), currency, false)} (${percent})`, dir };
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

const MARKET_WORDS = /\b(stocks?|stock market|dow|s&p|nasdaq|wall street|the fed|federal reserve|treasury yields?|bond yields?|bond market|inflation|oil prices?|crude oil|gold prices?|bitcoin|crypto|sensex|nifty|stock rally|market rally|sell-?off|ipo|interest rates?|rate (?:cut|hike)s?|jobs report|commodity prices?|rupee)\b/i;
const COMPANY_SUFFIX = /[,.]?\s+(corporation|corp|incorporated|inc|company|co|holdings|group|limited|ltd|llc|plc|n\.?v|class [a-z]|series \d+)\.?$/i;

const escape = (t: string) => t.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

/** What makes a story about your watchlist: each symbol and each company name (without "Inc." and the like) as a whole word.
 * Compiled once here, not per story. */
export function watchTerms(quotes: Quote[]): RegExp[] {
  const symbols = new Set<string>();
  const names = new Set<string>();
  for (const q of quotes) {
    const symbol = q.symbol.replace('^', '').replace(/\.[A-Z]{1,2}$/, '');  // "RELIANCE.NS" is written "Reliance" or "RELIANCE" in prose
    if (symbol.length >= 2) symbols.add(symbol);
    let name = q.name.trim();
    for (let next = name.replace(COMPANY_SUFFIX, ''); next !== name; next = name.replace(COMPANY_SUFFIX, '')) name = next;
    if (name.length >= 4 && name !== q.symbol) names.add(name);
  }
  // No lookbehind (iOS Safari before 16.4 throws on it). Symbols match as written; names in any case ("NVIDIA" / "Nvidia").
  const make = (t: string, flags: string) => new RegExp(`(?:^|[^A-Za-z0-9])${escape(t)}(?![A-Za-z0-9])`, flags);
  return [...[...symbols].map((t) => make(t, '')), ...[...names].map((t) => make(t, 'i'))];
}

/** Is this story market news: from a markets feed, or a headline about markets or something on your watchlist? */
export function isMarketNews(item: { title: string; subtopic?: string }, terms: RegExp[] = []): boolean {
  return item.subtopic === 'markets' || MARKET_WORDS.test(item.title) || terms.some((t) => t.test(item.title));
}

/** The next report of one watchlist symbol, from the private earnings file. */
export interface Earning {
  symbol: string;
  date: string;  // YYYY-MM-DD, the exchange's calendar day
  time: 'pre' | 'post' | 'tbd';  // before the open, after the close, or not announced
  eps: number | null;  // the consensus estimate
}

export interface Earnings {
  generated: string;
  items: Earning[];
}

const ISO_DAY = /^\d{4}-\d{2}-\d{2}$/;
const EARNINGS_MAX_AGE_MS = 3 * 24 * 3600_000;  // a file this old means the calendar has stopped updating: show nothing
export const EARNINGS_DAYS = 14;  // the Markets tab shows this far ahead; a symbol's own page shows any date

/** The earnings document, checked field by field: the file is not trusted, and a bad entry is dropped. */
export function parseEarnings(value: unknown, now: Date): Earnings | undefined {
  const v = value as Record<string, unknown> | null;
  if (!v || typeof v.generated !== 'string' || !Array.isArray(v.items)) return undefined;
  const age = now.getTime() - new Date(v.generated).getTime();
  if (!(age < EARNINGS_MAX_AGE_MS)) return undefined;  // also false for NaN
  const items: Earning[] = [];
  for (const raw of v.items as unknown[]) {
    const o = raw as Record<string, unknown> | null;
    if (!o || typeof o.symbol !== 'string' || typeof o.date !== 'string' || !ISO_DAY.test(o.date) || Number.isNaN(Date.parse(o.date))) continue;
    const time = o.time === 'pre' || o.time === 'post' ? o.time : 'tbd';
    items.push({ symbol: o.symbol, date: o.date, time, eps: typeof o.eps === 'number' && Number.isFinite(o.eps) ? o.eps : null });
  }
  return { generated: v.generated, items };
}

const pad = (n: number): string => String(n).padStart(2, '0');

/** A local calendar day as YYYY-MM-DD. */
export const dayKey = (d: Date): string => d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate());

const addDays = (d: Date, n: number): Date => new Date(d.getFullYear(), d.getMonth(), d.getDate() + n, 12);

/** "Today", "Tomorrow" or "Thu 19" for a report date, and whether it is today. */
export function earningDay(date: string, now: Date): { label: string; today: boolean } {
  if (date === dayKey(now)) return { label: 'Today', today: true };
  if (date === dayKey(addDays(now, 1))) return { label: 'Tomorrow', today: false };
  const [y = 0, m = 1, d = 1] = date.split('-').map(Number);
  return { label: new Date(y, m - 1, d, 12).toLocaleDateString(undefined, { weekday: 'short', day: 'numeric' }), today: false };
}

/** A report date for a symbol's own page, e.g. "Thu, Nov 19, 2026". */
export const earningDate = (date: string): string =>
  new Date(date + 'T12:00:00').toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric', year: 'numeric' });

export const earningTime = (time: Earning['time']): string => (time === 'pre' ? 'before open' : time === 'post' ? 'after close' : '');

/** An estimate as dollars: "$0.64", "−$0.12". */
export const epsLabel = (eps: number): string => (eps < 0 ? '−' : '') + '$' + Math.abs(eps).toFixed(2);

/** The reports from today on, soonest first, for the symbols in `shown`; `days` limits how far ahead (none: any date). */
export function upcoming(earnings: Earnings | undefined, shown: string[], now: Date, days?: number): Earning[] {
  if (!earnings) return [];
  const first = dayKey(now);
  const last = days === undefined ? '9999-12-31' : dayKey(addDays(now, days));
  const keep = new Set(shown);
  return earnings.items
    .filter((e) => keep.has(e.symbol) && e.date >= first && e.date <= last)
    .sort((a, b) => a.date.localeCompare(b.date) || a.symbol.localeCompare(b.symbol));
}

/** "open", "pre-open" (a weekday before 9:30 AM US Eastern) or "closed". `open` on a quote is frozen at build time, so a
 *  stale document is never "open". */
export function marketPhase(markets: Markets, now: Date): 'open' | 'pre-open' | 'closed' {
  const us = markets.tickers.filter((q) => q.currency === 'USD');  // a watchlist can hold stocks from other exchanges
  if (isFresh(markets.generated, now) && (us.length > 0 ? us : markets.tickers).some((q) => q.open)) return 'open';
  const parts = new Intl.DateTimeFormat('en-US', { timeZone: 'America/New_York', weekday: 'short', hour: 'numeric', minute: 'numeric', hourCycle: 'h23' }).formatToParts(now);
  const get = (type: string) => parts.find((p) => p.type === type)?.value ?? '';
  const minutes = Number(get('hour')) * 60 + Number(get('minute'));
  const weekday = !['Sat', 'Sun'].includes(get('weekday'));
  return weekday && minutes >= 4 * 60 && minutes < 9 * 60 + 30 ? 'pre-open' : 'closed';  // pre-market trading starts at 4:00 AM Eastern
}

export interface StripMove {
  symbol: string;
  text: string;
  dir: 'up' | 'down' | 'flat';
}

/** The watchlist's moves for the home strip: the biggest movers first (ties by symbol), at most `max`, and how many more there are.
 *  A move that rounds to 0.0% shows as flat, with no sign and no color. */
export function stripMoves(tickers: Quote[], max = 4): { moves: StripMove[]; more: number } {
  const moved = tickers
    .filter((q) => q.changePct !== null)
    .sort((a, b) => Math.abs(b.changePct ?? 0) - Math.abs(a.changePct ?? 0) || a.symbol.localeCompare(b.symbol));
  const moves = moved.slice(0, max).map((q): StripMove => {
    const pct = q.changePct ?? 0;
    const shown = Math.abs(pct).toFixed(1);
    if (Number(shown) === 0) return { symbol: q.symbol, text: '0.0%', dir: 'flat' };
    return pct > 0 ? { symbol: q.symbol, text: `+${shown}%`, dir: 'up' } : { symbol: q.symbol, text: `−${shown}%`, dir: 'down' };
  });
  return { moves, more: Math.max(moved.length - max, 0) };
}

/** "NVDA after the close" lines for the symbols that report today. */
export function earningsToday(earnings: Earnings | undefined, shown: string[], now: Date): string[] {
  const when = { pre: 'before the open', post: 'after the close', tbd: '' };
  return upcoming(earnings, shown, now, 0).map((e) => [e.symbol, when[e.time]].filter(Boolean).join(' '));
}
