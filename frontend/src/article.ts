export type BlockKind = 'p' | 'h' | 'li' | 'q';
export interface Block {
  t: BlockKind;
  x: string;
}
export type Articles = Record<string, Block[]>;

const KINDS = new Set<string>(['p', 'h', 'li', 'q']);
const WORDS_PER_MINUTE = 220;

function validBlock(v: unknown): v is Block {
  const b = v as Partial<Block> | null;
  return !!b && typeof b.t === 'string' && KINDS.has(b.t) && typeof b.x === 'string' && b.x.trim() !== '';
}

/** The articles document, keeping only well-formed blocks (plain text: the page never renders HTML from the feed). */
export function parseArticles(value: unknown): Articles | undefined {
  const v = value as { articles?: unknown } | null;
  if (!v || typeof v.articles !== 'object' || v.articles === null || Array.isArray(v.articles)) return undefined;
  const out: Articles = Object.create(null) as Articles;  // no inherited keys: an id like "constructor" cannot match
  for (const [id, blocks] of Object.entries(v.articles)) {
    if (Array.isArray(blocks)) {
      const good = blocks.filter(validBlock);
      if (good.length > 0) out[id] = good;
    }
  }
  return out;
}

export function readingMinutes(blocks: Block[]): number {
  const words = blocks.reduce((n, b) => n + b.x.split(/\s+/).filter(Boolean).length, 0);
  return Math.max(1, Math.round(words / WORDS_PER_MINUTE));
}

export type Group = { kind: 'p' | 'h' | 'q'; text: string } | { kind: 'list'; items: string[] };

/** Consecutive list items become one list. */
export function groupBlocks(blocks: Block[]): Group[] {
  const out: Group[] = [];
  for (const b of blocks) {
    const last = out[out.length - 1];
    if (b.t === 'li') {
      if (last?.kind === 'list') last.items.push(b.x);
      else out.push({ kind: 'list', items: [b.x] });
    } else {
      out.push({ kind: b.t, text: b.x });
    }
  }
  return out;
}
