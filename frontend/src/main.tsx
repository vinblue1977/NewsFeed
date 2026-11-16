import { render } from 'preact';

import { App } from './App';
import './styles.css';

const root = document.getElementById('app');
if (root) render(<App />, root);

// Offline access: the service worker keeps the app and the last stories on the phone (production builds only).
if (import.meta.env.PROD && 'serviceWorker' in navigator) {
  window.addEventListener('load', () => { void navigator.serviceWorker.register('/sw.js').catch(() => undefined); });
}
