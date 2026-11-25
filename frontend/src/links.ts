/** Attributes for a link that leaves the app. In the iPhone home-screen app it opens in the same window: with target="_blank"
 *  iOS opens an empty window first, so Back showed a blank page before the app. Anywhere else (a browser tab, an installed
 *  Android or desktop app) it still opens a new tab, so the feed stays where it was. */
export function externalAttrs(standalone: boolean): { target?: string; rel: string } {
  return standalone ? { rel: 'noopener noreferrer' } : { target: '_blank', rel: 'noopener noreferrer' };
}

/** `href` plus the right attributes; in-app "#/..." links get none. */
export function linkAttrs(href: string, standalone: boolean): { href: string; target?: string; rel?: string } {
  return href.startsWith('#') ? { href } : { href, ...externalAttrs(standalone) };
}

/** True in the iPhone home-screen app (`navigator.standalone`, which only iOS Safari has). */
export function isStandalone(nav: { standalone?: boolean } | undefined = typeof navigator === 'undefined' ? undefined : (navigator as { standalone?: boolean })): boolean {
  try {
    return nav?.standalone === true;
  } catch {
    return false;
  }
}
