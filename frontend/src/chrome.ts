import { useEffect, useState } from 'preact/hooks';

/** Reading screens hide their bars while you scroll down and bring them back when you scroll up. */
export interface Chrome {
  hidden: boolean;
  anchor: number;  // the scroll position the next move is measured from
}

export const SHOW_NEAR_TOP = 60;  // always shown near the top of the page
export const SHOW_NEAR_END = 8;  // and at the very end
export const THRESHOLD = 8;  // how far you must scroll before the bars react
export const PROGRESS_VAR = '--read-progress';

/** The new state for a scroll to `y` on a page that can scroll `max` px. Positions outside the page (the iOS rubber band) are ignored. */
export function nextChrome(state: Chrome, y: number, max: number): Chrome {
  if (y < 0 || y > max) return state;
  if (y <= SHOW_NEAR_TOP || max - y <= SHOW_NEAR_END) return { hidden: false, anchor: y };
  const delta = y - state.anchor;
  if (delta > THRESHOLD) return { hidden: true, anchor: y };
  if (delta < -THRESHOLD) return { hidden: false, anchor: y };
  // a small move: keep following the page in the direction the bars already point, so a slow scroll still adds up
  if ((state.hidden && delta > 0) || (!state.hidden && delta < 0)) return { hidden: state.hidden, anchor: y };
  return state;
}

/** How far through the page you are, 0 to 1. */
export function progressOf(y: number, max: number): number {
  return max > 0 ? Math.min(1, Math.max(0, y / max)) : 0;
}

/** Scroll-driven bars for a reading screen. `resetKey` changes with the screen, which shows the bars again.
 * The reading progress is written straight to a CSS variable, so scrolling does not re-render the page. */
export function useChrome(active: boolean, resetKey: string): { hidden: boolean; show: () => void } {
  const [state, setState] = useState<Chrome & { key: string }>({ hidden: false, anchor: 0, key: resetKey });
  useEffect(() => {
    setState({ hidden: false, anchor: 0, key: resetKey });
    const root = document.documentElement;
    root.style.removeProperty(PROGRESS_VAR);
    if (!active) return undefined;
    let frame = 0;
    const update = () => {
      frame = 0;
      const y = window.scrollY;
      const max = Math.max(0, root.scrollHeight - window.innerHeight);
      root.style.setProperty(PROGRESS_VAR, String(progressOf(y, max)));
      setState((prev) => {
        const next = nextChrome(prev, y, max);
        return next === prev ? prev : { ...next, key: resetKey };
      });
    };
    const schedule = () => {
      if (!frame) frame = requestAnimationFrame(update);  // at most once per frame
    };
    window.addEventListener('scroll', schedule, { passive: true });
    const sizeWatcher = typeof ResizeObserver === 'function' ? new ResizeObserver(schedule) : undefined;  // the article loads after the page
    sizeWatcher?.observe(document.body);
    return () => {
      window.removeEventListener('scroll', schedule);
      sizeWatcher?.disconnect();
      if (frame) cancelAnimationFrame(frame);
      root.style.removeProperty(PROGRESS_VAR);
    };
  }, [active, resetKey]);
  return {
    hidden: active && state.key === resetKey && state.hidden,  // never carry the previous screen's state over
    show: () => setState((s) => ({ hidden: false, anchor: window.scrollY, key: s.key })),  // measure the next move from here
  };
}
