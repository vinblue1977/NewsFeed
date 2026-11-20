import { describe, expect, it } from 'vitest';
import { contrast, lighten, TEAM_PAIRS, teamTheme, themeVars } from './theme';

describe('teamTheme', () => {
  it('finds a team by its nickname or full name, any case and spacing', () => {
    const bears = teamTheme(['Bears']);
    expect(bears).toMatchObject({ accent: '#f37733', bg: '#0f1730' });
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

  it('gives every NFL team its own colours', () => {
    const seen = new Set(TEAM_PAIRS.map(([bg, accent]) => `${bg}/${accent}`));
    expect(seen.size).toBe(TEAM_PAIRS.length);
  });

  it('puts readable text on the accent: black or white, whichever contrasts more', () => {
    expect(teamTheme(['Packers'])?.onAccent).toBe('#000000');  // a bright gold
    expect(teamTheme(['Chiefs'])?.onAccent).toBe('#000000');
    for (const { accent, onAccent } of TEAM_PAIRS.map(([, a]) => ({ accent: a, onAccent: contrast('#000000', a) >= contrast('#ffffff', a) ? '#000000' : '#ffffff' }))) {
      expect(contrast(onAccent, accent), accent).toBeGreaterThanOrEqual(4.5);
    }
  });

  it('keeps every team readable: the accent as text on the background, and the normal light text on it', () => {
    expect(TEAM_PAIRS.length).toBeGreaterThan(40);
    for (const [bg, accent] of TEAM_PAIRS) {
      expect(contrast(accent, bg), `${accent} on ${bg}`).toBeGreaterThanOrEqual(4.5);
      expect(contrast('#e8eaed', bg), `text on ${bg}`).toBeGreaterThanOrEqual(7);
    }
  });

  it('keeps the muted text readable on the card and chip surfaces', () => {
    for (const [bg] of TEAM_PAIRS) {
      for (const amount of [0.05, 0.08]) expect(contrast('#9aa0a6', lighten(bg, amount)), `muted on ${bg} +${amount}`).toBeGreaterThanOrEqual(4.5);
    }
  });

  it('keeps the accent readable on the card surface too', () => {
    for (const [bg, accent] of TEAM_PAIRS) {
      expect(contrast(accent, lighten(bg, 0.11)), `${accent} on lines and cards of ${bg}`).toBeGreaterThanOrEqual(4);  // the lightest surface (the line) is the hardest case
    }
  });

  it('turns a theme into the CSS variables the page uses', () => {
    const theme = teamTheme(['Bears']);
    if (!theme) throw new Error('no Bears theme');
    const vars = themeVars(theme);
    expect(Object.keys(vars).sort()).toEqual(['--accent', '--bg', '--card', '--chip', '--line', '--on-accent']);
    expect(vars['--bg']).toBe('#0f1730');
    expect(vars['--card']).toMatch(/^#[0-9a-f]{6}$/);
  });
});
