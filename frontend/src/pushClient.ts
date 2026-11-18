/** The browser side of Web Push: reads what this device supports and asks for the subscription. The decisions are in push.ts. */
import { keyBytes, readSubscription, vapidReady, VAPID_PUBLIC_KEY, type PushEnv, type Subscription } from './push';

const isIos = (): boolean => /iPad|iPhone|iPod/.test(navigator.userAgent) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
const isStandalone = (): boolean =>
  (navigator as { standalone?: boolean }).standalone === true || (typeof matchMedia === 'function' && matchMedia('(display-mode: standalone)').matches);

/** What this device supports and whether it is already subscribed. Never throws. */
export async function readEnv(): Promise<{ env: PushEnv; sub: Subscription | undefined }> {
  const hasServiceWorker = 'serviceWorker' in navigator;
  const hasPushManager = 'PushManager' in window;
  const hasNotification = 'Notification' in window;
  let sub: Subscription | undefined;
  if (hasServiceWorker && hasPushManager) {
    try {
      const reg = await navigator.serviceWorker.getRegistration();
      const current = await reg?.pushManager.getSubscription();
      sub = readSubscription(current?.toJSON());
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

/** Must be called from a tap: asks for permission, then subscribes. Undefined if the permission was not given. */
export async function enable(): Promise<Subscription | undefined> {
  if ((await Notification.requestPermission()) !== 'granted') return undefined;
  const reg = await navigator.serviceWorker.ready;
  const existing = await reg.pushManager.getSubscription();
  const made = existing ?? (await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: keyBytes(VAPID_PUBLIC_KEY) }));
  return readSubscription(made.toJSON());
}

/** Stops notifications on this device (the user then also deletes the SSM parameter: docs/PUSH.md). */
export async function disable(): Promise<void> {
  const reg = await navigator.serviceWorker.getRegistration();
  await (await reg?.pushManager.getSubscription())?.unsubscribe();
}
