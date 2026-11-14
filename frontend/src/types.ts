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

export interface Feed {
  generated: string;
  items: Item[];
  clusters: Cluster[];
}
