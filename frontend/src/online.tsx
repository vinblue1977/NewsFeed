import { useEffect, useState } from 'preact/hooks';

/** Whether the phone says it has a connection. `false` is reliable; `true` can still mean a dead Wi-Fi, so this only drives a notice. */
export function useOnline(): boolean {
  const [online, setOnline] = useState(() => navigator.onLine !== false);
  useEffect(() => {
    const on = () => setOnline(true);
    const off = () => setOnline(false);
    window.addEventListener('online', on);
    window.addEventListener('offline', off);
    return () => {
      window.removeEventListener('online', on);
      window.removeEventListener('offline', off);
    };
  }, []);
  return online;
}

/** A slim bar at the top while offline: what is on screen is the copy kept on the phone. */
export function OfflineBar() {
  const online = useOnline();
  if (online) return null;
  return <div class="offline" role="status">You're offline. Showing the stories saved on this phone.</div>;
}
