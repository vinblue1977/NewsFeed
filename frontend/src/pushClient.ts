/** The browser side of Web Push: reads what this device supports and asks for the subscription. The decisions are in push.ts. */
import { keyBytes, readSubscription, sameKey, vapidReady, VAPID_PUBLIC_KEY, type PushEnv, type Subscription } from './push';

const READY_WAIT_MS = 5000;

const isIos = (): boolean => /iPad|iPhone|iPod/.test(navigator.userAgent) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
const isStandalone = (): boolean =>
  (navigator as { standalone?: boolean }).standalone === true || (typeof matchMedia === 'function' && matchMedia('(display-mode: standalone)').matches);

/** What this device supports and whether it is already subscribed with the current key. Never throws. */
export async function readEnv(): Promise<{ env: PushEnv; sub: Subscription | undefined }> {
  const hasServiceWorker = 'serviceWorker' in navigator;
  const hasPushManager = 'PushManager' in window;
  const hasNotification = 'Notification' in window;
  let sub: Subscription | undefined;
  if (hasServiceWorker && hasPushManager) {
    try {
      const reg = await navigator.serviceWorker.getRegistration();
      const current = await reg?.pushManager.getSubscription();
      if (current && sameKey(current.options.applicationServerKey)) sub = readSubscription(current.toJSON());  // one made with an old key is not "on"
    } catch {
      sub = undefined;
    }
  }
  const permission = hasNotification ? Notification.permission : 'default';
  return {
    env: { hasServiceWorker, hasPushManager, hasNotification, permission: permission === 'granted' || permission === 'denied' ? permission : 'default', standalone: isStandalone(), ios: isIos(), subscribed: sub !== undefined, keyReady: vapidReady() },
    sub,
  };
}

/** The service worker once it is running; an error if there is none (the dev server) or it takes too long, so a tap never hangs. */
async function worker(): Promise<ServiceWorkerRegistration> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  const timeout = new Promise<never>((_, reject) => { timer = setTimeout(() => reject(new Error('The app is not ready for notifications yet. Reload and try again.')), READY_WAIT_MS); });
  try {
    return await Promise.race([navigator.serviceWorker.ready, timeout]);
  } finally {
    clearTimeout(timer);
  }
}

/** Must be called from a tap: asks for permission, then subscribes. Undefined if the permission was not given or the
 *  subscription was incomplete. */
export async function enable(): Promise<Subscription | undefined> {
  if ((await Notification.requestPermission()) !== 'granted') return undefined;
  const reg = await worker();
  let current = await reg.pushManager.getSubscription();
  if (current && !sameKey(current.options.applicationServerKey)) {  // made with another key: pushes to it would be refused
    await current.unsubscribe();
    current = null;
  }
  const made = current ?? (await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: keyBytes(VAPID_PUBLIC_KEY) }));
  return readSubscription(made.toJSON());
}

/** Stops notifications on this device (the user then also deletes the SSM parameter: docs/PUSH.md). */
export async function disable(): Promise<void> {
  const reg = await navigator.serviceWorker.getRegistration();
  await (await reg?.pushManager.getSubscription())?.unsubscribe();
}
