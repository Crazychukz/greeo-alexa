import { InjectionToken } from '@angular/core';

/**
 * Where the simulator API lives. The dev server proxies /api to the backend
 * (proxy.conf.json), so the default needs no CORS. Override it in app.config.ts
 * for a deployed backend on another origin.
 */
export const GREEO_API_BASE = new InjectionToken<string>('GREEO_API_BASE', {
  providedIn: 'root',
  factory: () => '/api/simulator',
});
