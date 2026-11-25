export type Topic = 'us' | 'world' | 'india' | 'sports' | 'tech' | 'business' | 'entertainment' | 'science' | 'local' | 'chicago';

export interface Item {
  id: string;
  title: string;
  url: string;
  summary: string;
  published: string;
  source: string;
  topic: Topic;
  cluster?: string;
  subtopic?: string;
  metered?: boolean;
  full?: boolean;  // the article's full text is in articles.json
  img?: string;  // file name of the picture, a copy in our own bucket (see imageSrc)
}

export interface Cluster {
  id: string;
  title: string;
  topic: Topic;
  lead: string;
  published: string;
  sources: number;
  items: string[];
}

/** What the last ingest run said about one feed: `name` is missing for a local feed that produced no stories (its host could give
 * away the town), and in a feed.json written before names were added. */
export interface SourceStatus {
  name?: string;
  ok: boolean;
  items: number;
  filtered?: number;
  blocked?: number;
  duplicates?: number;  // fetched fine, but another feed had the story first
  error?: string;
}

export interface Feed {
  generated: string;
  items: Item[];
  clusters: Cluster[];
  sources?: Record<string, SourceStatus>;
}
