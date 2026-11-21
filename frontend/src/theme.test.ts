import { describe, expect, it } from 'vitest';
import { contrast, TEAM_ACCENTS, teamTheme, themeVars } from './theme';

describe('teamTheme', () => {
  it('finds a team by its nickname or full name, any case and spacing', () => {
    const bears = teamTheme(['Bears']);
    expect(bears).toMatchObject({ accent: '#f37733' });
    expect(teamTheme(['  chicago   BEARS '])).toEqual(bears);
    expect(teamTheme(['Chicago Bears'])).toEqual(bears);
    expect(teamTheme(['India'])?.accent).toBe('#54a7ff');
  });

  it('follows the first team only, and falls back when it is unknown or there is none', () => {
    expect(teamTheme(['Bears', 'India'])?.accent).toBe('#f37733');
    expect(teamTheme(['Sinner', 'Bears'])).toBeUndefined();  // the first one decides; no colours for a player
    expect(teamTheme([])).toBeUndefined();
    expect(teamTheme([''])).toBeUndefined();
  });

  it('matches a whole name only, so another sport\'s team of the same nickname is left alone', () => {
    expect(teamTheme(['Bearsville'])).toBeUndefined();
    expect(teamTheme(['Indiana'])).toBeUndefined();
    for (const other of ['San Francisco Giants', 'St. Louis Cardinals', 'Winnipeg Jets', 'Florida Panthers', 'New England', 'Team India', 'Women England']) {
      expect(teamTheme([other]), other).toBeUndefined();
    }
    expect(teamTheme(['NY Giants'])).toEqual(teamTheme(['New York Giants']));
  });

  it('puts readable text on the accent: black or white, whichever contrasts more', () => {
    expect(teamTheme(['Packers'])?.onAccent).toBe('#000000');  // a bright gold
    expect(teamTheme(['Chiefs'])?.onAccent).toBe('#000000');
    for (const { accent, onAccent } of TEAM_ACCENTS.map((a) => ({ accent: a, onAccent: contrast('#000000', a) >= contrast('#ffffff', a) ? '#000000' : '#ffffff' }))) {
      expect(contrast(onAccent, accent), accent).toBeGreaterThanOrEqual(4.5);
    }
  });

  it('keeps every accent readable as text on the lightest card colour (the top of the card gradient)', () => {
    expect(TEAM_ACCENTS.length).toBeGreaterThan(40);
    for (const accent of TEAM_ACCENTS) expect(contrast(accent, '#272a2e'), accent).toBeGreaterThanOrEqual(4.5);
  });

  it('turns a theme into the CSS variables the page uses', () => {
    const theme = teamTheme(['Bears']);
    if (!theme) throw new Error('no Bears theme');
    const vars = themeVars(theme);
    expect(Object.keys(vars).sort()).toEqual(['--accent', '--on-accent']);  // only the accent: the page stays black
    expect(vars['--accent']).toBe('#f37733');
  });
});
