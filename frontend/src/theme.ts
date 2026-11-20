/** Team colours for the Sports tab: its accent and background follow the first team in My teams. Nothing leaves the phone. */

export interface Theme {
  accent: string;  // links, active chips, buttons
  onAccent: string;  // text on the accent: black or white, whichever reads better
  bg: string;
  card: string;
  line: string;
  chip: string;
}

/** [names the team answers to, background (a dark tint of the team's main colour), accent (a bright team colour)]. A name matches a typed team
 * only when it is equal to it ("Bears" and "Chicago Bears" both find the Bears; "San Francisco Giants" finds nothing, as the Giants here are New York's). Every pair is checked for readable contrast in the tests. */
const TEAMS: [string[], string, string][] = [
  [['arizona cardinals', 'cardinals'], '#2a0f16', '#e87588'],
  [['atlanta falcons', 'falcons'], '#1f1012', '#f36f78'],
  [['baltimore ravens', 'ravens'], '#1a1330', '#b69bff'],
  [['buffalo bills', 'bills'], '#0b1a38', '#629fff'],
  [['carolina panthers', 'panthers'], '#0a1b25', '#3cb4ea'],
  [['chicago bears', 'bears'], '#0f1730', '#f37733'],
  [['cincinnati bengals', 'bengals'], '#1c1409', '#ff7a1a'],
  [['cleveland browns', 'browns'], '#1d130c', '#ff6a3a'],
  [['dallas cowboys', 'cowboys'], '#0c1a2e', '#7fa6d6'],
  [['denver broncos', 'broncos'], '#0f1a30', '#ff7a2e'],
  [['detroit lions', 'lions'], '#0a1f33', '#51abe1'],
  [['green bay packers', 'packers'], '#0f2418', '#ffc83d'],
  [['houston texans', 'texans'], '#0b1830', '#e87b8a'],
  [['indianapolis colts', 'colts'], '#0b1b36', '#5aa0ff'],
  [['jacksonville jaguars', 'jaguars'], '#0c1f24', '#2fb7b0'],
  [['kansas city chiefs', 'chiefs'], '#2a0e14', '#ff6876'],
  [['las vegas raiders', 'raiders'], '#121212', '#c0c4c8'],
  [['los angeles chargers', 'la chargers', 'chargers'], '#0a1f3a', '#ffc20e'],
  [['los angeles rams', 'la rams', 'rams'], '#0b1c3a', '#ffb81c'],
  [['miami dolphins', 'dolphins'], '#07232b', '#2ad0c5'],
  [['minnesota vikings', 'vikings'], '#1b1230', '#ffc62f'],
  [['new england patriots', 'patriots'], '#0b1830', '#b8c4d6'],
  [['new orleans saints', 'saints'], '#1a1710', '#d3bc8d'],
  [['new york giants', 'ny giants', 'giants'], '#0c1a38', '#6a9bff'],
  [['new york jets', 'ny jets', 'jets'], '#0a2a22', '#3dd68c'],
  [['philadelphia eagles', 'eagles'], '#07262a', '#3ec9b0'],
  [['pittsburgh steelers', 'steelers'], '#141414', '#ffb612'],
  [['san francisco 49ers', '49ers'], '#26100f', '#d9b66a'],
  [['seattle seahawks', 'seahawks'], '#0a1a2c', '#69be28'],
  [['tampa bay buccaneers', 'buccaneers', 'bucs'], '#25100f', '#ff6758'],
  [['tennessee titans', 'titans'], '#0b1b33', '#66a2df'],
  [['washington commanders', 'commanders'], '#2a1218', '#ffb612'],
  // cricket nations
  [['india'], '#0a1f4a', '#54a7ff'],
  [['australia'], '#1d1a08', '#ffcd00'],
  [['england'], '#0c1a3a', '#6fa0ff'],
  [['pakistan'], '#0b2416', '#4cd07d'],
  [['south africa'], '#0b2416', '#ffb81c'],
  [['new zealand'], '#111214', '#cfd2d6'],
  [['sri lanka'], '#0b1a3a', '#ffc20e'],
  [['bangladesh'], '#0b2416', '#ff797c'],
  [['west indies'], '#2a0f1c', '#ffc72c'],
  [['afghanistan'], '#0b2a1c', '#4cc9f0'],
];

const norm = (s: string): string => s.toLowerCase().replace(/\s+/g, ' ').trim();

const rgb = (color: string): [number, number, number] => [1, 3, 5].map((i) => parseInt(color.slice(i, i + 2), 16)) as [number, number, number];
const toHex = (c: number[]): string => `#${c.map((v) => Math.round(v).toString(16).padStart(2, '0')).join('')}`;

/** `color` mixed towards white by `amount` (0 to 1). */
export function lighten(color: string, amount: number): string {
  return toHex(rgb(color).map((v) => v + (255 - v) * amount));
}

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
  const [, bg, accent] = hit;
  const onAccent = contrast('#000000', accent) >= contrast('#ffffff', accent) ? '#000000' : '#ffffff';
  return { accent, onAccent, bg, card: lighten(bg, 0.05), line: lighten(bg, 0.11), chip: lighten(bg, 0.08) };
}

/** The CSS variables a theme sets on the page. */
export function themeVars(t: Theme): Record<string, string> {
  return { '--accent': t.accent, '--on-accent': t.onAccent, '--bg': t.bg, '--card': t.card, '--line': t.line, '--chip': t.chip };
}

export const THEME_VARS = ['--accent', '--on-accent', '--bg', '--card', '--line', '--chip'] as const;
export const TEAM_PAIRS: readonly (readonly [string, string])[] = TEAMS.map(([, bg, accent]) => [bg, accent]);
