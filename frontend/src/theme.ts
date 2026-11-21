/** Team colours for the Sports tab: its accent follows the first team in My teams (the page stays black). Nothing leaves the phone. */

export interface Theme {
  accent: string;  // links, active chips, buttons
  onAccent: string;  // text on the accent: black or white, whichever reads better
}

/** [names the team answers to, accent (a bright team colour)]. A name matches a typed team
 * only when it is equal to it ("Bears" and "Chicago Bears" both find the Bears; "San Francisco Giants" finds nothing, as the Giants here are New York's). Every accent is checked for readable contrast on the card surfaces in the tests. */
const TEAMS: [string[], string][] = [
  [['arizona cardinals', 'cardinals'], '#e87588'],
  [['atlanta falcons', 'falcons'], '#f36f78'],
  [['baltimore ravens', 'ravens'], '#b69bff'],
  [['buffalo bills', 'bills'], '#629fff'],
  [['carolina panthers', 'panthers'], '#3cb4ea'],
  [['chicago bears', 'bears'], '#f37733'],
  [['cincinnati bengals', 'bengals'], '#ff7a1a'],
  [['cleveland browns', 'browns'], '#ff6a3a'],
  [['dallas cowboys', 'cowboys'], '#7fa6d6'],
  [['denver broncos', 'broncos'], '#ff7a2e'],
  [['detroit lions', 'lions'], '#51abe1'],
  [['green bay packers', 'packers'], '#ffc83d'],
  [['houston texans', 'texans'], '#e87b8a'],
  [['indianapolis colts', 'colts'], '#5aa0ff'],
  [['jacksonville jaguars', 'jaguars'], '#2fb7b0'],
  [['kansas city chiefs', 'chiefs'], '#ff6876'],
  [['las vegas raiders', 'raiders'], '#c0c4c8'],
  [['los angeles chargers', 'la chargers', 'chargers'], '#ffc20e'],
  [['los angeles rams', 'la rams', 'rams'], '#ffb81c'],
  [['miami dolphins', 'dolphins'], '#2ad0c5'],
  [['minnesota vikings', 'vikings'], '#ffc62f'],
  [['new england patriots', 'patriots'], '#b8c4d6'],
  [['new orleans saints', 'saints'], '#d3bc8d'],
  [['new york giants', 'ny giants', 'giants'], '#6a9bff'],
  [['new york jets', 'ny jets', 'jets'], '#3dd68c'],
  [['philadelphia eagles', 'eagles'], '#3ec9b0'],
  [['pittsburgh steelers', 'steelers'], '#ffb612'],
  [['san francisco 49ers', '49ers'], '#d9b66a'],
  [['seattle seahawks', 'seahawks'], '#69be28'],
  [['tampa bay buccaneers', 'buccaneers', 'bucs'], '#ff6758'],
  [['tennessee titans', 'titans'], '#66a2df'],
  [['washington commanders', 'commanders'], '#ffb612'],
  // cricket nations
  [['india'], '#54a7ff'],
  [['australia'], '#ffcd00'],
  [['england'], '#6fa0ff'],
  [['pakistan'], '#4cd07d'],
  [['south africa'], '#ffb81c'],
  [['new zealand'], '#cfd2d6'],
  [['sri lanka'], '#ffc20e'],
  [['bangladesh'], '#ff797c'],
  [['west indies'], '#ffc72c'],
  [['afghanistan'], '#4cc9f0'],
];

const norm = (s: string): string => s.toLowerCase().replace(/\s+/g, ' ').trim();

const rgb = (color: string): [number, number, number] => [1, 3, 5].map((i) => parseInt(color.slice(i, i + 2), 16)) as [number, number, number];

/** WCAG relative luminance of a #rrggbb colour. */
function luminance(color: string): number {
  const [r, g, b] = rgb(color).map((v) => {
    const s = v / 255;
    return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  }) as [number, number, number];
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

/** WCAG contrast ratio of two #rrggbb colours (1 to 21). */
export function contrast(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x) as [number, number];
  return (hi + 0.05) / (lo + 0.05);
}

/** The theme for the first of `teams`, or undefined when it is not a team we have colours for (the normal theme stays). */
export function teamTheme(teams: string[]): Theme | undefined {
  const first = norm(teams[0] ?? '');
  if (!first) return undefined;
  const hit = TEAMS.find(([names]) => names.includes(first));
  if (!hit) return undefined;
  const [, accent] = hit;
  const onAccent = contrast('#000000', accent) >= contrast('#ffffff', accent) ? '#000000' : '#ffffff';
  return { accent, onAccent };
}

/** The CSS variables a theme sets on the page: only the accent. The page stays black like every other tab. */
export function themeVars(t: Theme): Record<string, string> {
  return { '--accent': t.accent, '--on-accent': t.onAccent };
}

export const THEME_VARS = ['--accent', '--on-accent'] as const;
export const TEAM_ACCENTS: readonly string[] = TEAMS.map(([, accent]) => accent);
