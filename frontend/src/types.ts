export type Topic = 'us' | 'world' | 'india' | 'sports' | 'tech' | 'business' | 'local';

export interface Item {
  id: string;
  title: string;
  url: string;
  summary: string;
  published: string;
  source: string;
  topic: Topic;
  cluster?: string;
  place?: string;
  subtopic?: string;
  metered?: boolean;
  full?: boolean;  // the article's full text is in articles.json
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

export interface Feed {
  generated: string;
  items: Item[];
  clusters: Cluster[];
}
