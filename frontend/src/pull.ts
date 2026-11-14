import { useEffect, useRef, useState } from 'preact/hooks';

/** Pull-to-refresh state machine: a pull counts when it starts at the very top of the page and is mostly downward. */
export const TRIGGER = 70;  // px of pull that starts a refresh
export const MAX_PULL = 110;  // the indicator stops following the finger here
export const RESISTANCE = 0.5;  // the finger moves twice as far as the indicator

/** The indicator distance for a finger that has moved `dy` down and `dx` sideways; 0 if this is not a pull. */
export function pullDistance(dy: number, dx: number): number {
  if (dy <= 0 || Math.abs(dx) > dy) return 0;  // upward or sideways: an ordinary scroll
  return Math.min(MAX_PULL, dy * RESISTANCE * 2);
}

export const shouldRefresh = (distance: number): boolean => distance >= TRIGGER;

/** Pull down at the top of the page to run `onRefresh`. Returns how far the indicator is pulled and whether it is spinning. */
export function usePullToRefresh(enabled: boolean, onRefresh: () => void): { distance: number; spinning: boolean } {
  const [distance, setDistance] = useState(0);
  const [spinning, setSpinning] = useState(false);
  const start = useRef<{ x: number; y: number } | undefined>(undefined);
  const latest = useRef(onRefresh);
  latest.current = onRefresh;
  const last = useRef(0);
  const spinTimer = useRef<number | undefined>(undefined);
  useEffect(() => () => clearTimeout(spinTimer.current), []);
  useEffect(() => {
    if (!enabled) return;
    const down = (e: TouchEvent) => {
      const t = e.touches[0];
      start.current = window.scrollY <= 0 && t ? { x: t.clientX, y: t.clientY } : undefined;
    };
    const move = (e: TouchEvent) => {
      const t = e.touches[0];
      if (!start.current || !t || window.scrollY > 0) { start.current = undefined; setDistance(0); return; }
      last.current = pullDistance(t.clientY - start.current.y, t.clientX - start.current.x);
      setDistance(last.current);
    };
    const up = () => {
      const go = start.current !== undefined && shouldRefresh(last.current);
      start.current = undefined;
      last.current = 0;
      setDistance(0);
      if (!go) return;
      setSpinning(true);
      latest.current();
      clearTimeout(spinTimer.current);
      spinTimer.current = window.setTimeout(() => setSpinning(false), 900);  // the loads report no completion; a short spin shows it was heard
    };
    window.addEventListener('touchstart', down, { passive: true });
    window.addEventListener('touchmove', move, { passive: true });
    window.addEventListener('touchend', up, { passive: true });
    window.addEventListener('touchcancel', up, { passive: true });
    return () => {
      window.removeEventListener('touchstart', down);
      window.removeEventListener('touchmove', move);
      window.removeEventListener('touchend', up);
      window.removeEventListener('touchcancel', up);
    };
  }, [enabled]);
  return { distance, spinning };
}
