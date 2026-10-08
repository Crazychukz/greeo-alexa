import { HttpClient } from '@angular/common/http';
import {
  Component,
  DOCUMENT,
  DestroyRef,
  ElementRef,
  effect,
  inject,
  signal,
  viewChild,
} from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { NavigationEnd, Router, RouterLink, RouterOutlet } from '@angular/router';
import { filter, map } from 'rxjs';

import { AboutPanel } from './shared/about-panel/about-panel';
import { FrictionPanel } from './shared/friction-panel/friction-panel';

/** Open-Meteo: free, no API key, CORS enabled. https://open-meteo.com/en/docs */
const WEATHER_URL = 'https://api.open-meteo.com/v1/forecast';
const WEATHER_REFRESH_MS = 30 * 60 * 1000;
/** GeoJS: approximate location from the IP address; free, no key, CORS enabled. */
const APPROX_LOCATION_URL = 'https://get.geojs.io/v1/ip/geo.json';

interface GeoJsLocation {
  latitude: string;
  longitude: string;
}

/** A dark (graphite) device on a light page, or a light (silver) device on a dark page. */
export type DeviceFinish = 'dark' | 'light';
const FINISH_KEY = 'greeo.deviceFinish';

interface OpenMeteoCurrent {
  current: { temperature_2m: number };
}

/** The app shell: the Greeo device, with each route shown on its screen. */
@Component({
  imports: [RouterOutlet, RouterLink, AboutPanel, FrictionPanel],
  selector: 'app-root',
  styleUrl: './app.scss',
  templateUrl: './app.html',
})
export class App {
  private readonly document = inject(DOCUMENT);
  private readonly http = inject(HttpClient);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly isFullscreen = signal(false);
  private readonly router = inject(Router);
  /** True on the home screen; the Home button shows everywhere else. */
  protected readonly onHome = toSignal(
    this.router.events.pipe(
      filter((event) => event instanceof NavigationEnd),
      map(() => isHome(this.router.url)),
    ),
    { initialValue: isHome(this.router.url) },
  );
  /** The panel open over the screen: About (the info button) or the friction log (menu). */
  protected readonly sheet = signal<'about' | 'friction' | null>(null);
  private readonly aboutButton = viewChild.required<ElementRef<HTMLButtonElement>>('aboutButton');
  private readonly frictionButton =
    viewChild.required<ElementRef<HTMLButtonElement>>('frictionButton');
  protected readonly deviceFinish = signal<DeviceFinish>(readStoredFinish());
  protected readonly appTime = signal(formatClockTime(new Date()));
  protected readonly appWeather = signal<number | null>(null);

  constructor() {
    this.document.addEventListener('fullscreenchange', () =>
      this.isFullscreen.set(this.document.fullscreenElement !== null),
    );
    this.startClock();
    this.startWeather();
    effect(() => {
      const finish = this.deviceFinish();
      this.document.documentElement.dataset['device'] = finish;
      storeFinish(finish);
    });
  }

  /** Close the open panel and give focus back to the button that opened it. */
  protected closeSheet(): void {
    const opener = this.sheet() === 'about' ? this.aboutButton() : this.frictionButton();
    this.sheet.set(null);
    opener.nativeElement.focus();
  }

  protected toggleDeviceFinish(): void {
    this.deviceFinish.update((finish) => (finish === 'dark' ? 'light' : 'dark'));
  }

  protected toggleFullscreen(): void {
    if (this.document.fullscreenElement) {
      void this.document.exitFullscreen();
    } else {
      void this.document.documentElement.requestFullscreen?.().catch(() => undefined);
    }
  }

  private startClock(): void {
    let timer: ReturnType<typeof setTimeout>;
    const tick = () => {
      const now = new Date();
      this.appTime.set(formatClockTime(now));
      timer = setTimeout(tick, 60_000 - (now.getSeconds() * 1000 + now.getMilliseconds()));
    };
    tick();
    this.destroyRef.onDestroy(() => clearTimeout(timer));
  }

  /**
   * Find where the listener is, then fetch the temperature there and refresh it every
   * 30 minutes. Precise location needs the browser's permission; if that is refused or
   * unavailable (including macOS Location Services being off for the browser), fall back
   * to an approximate, city-level location from the IP address, which needs no prompt.
   */
  private startWeather(): void {
    const begin = (latitude: number, longitude: number) => {
      const load = () => this.loadWeather(latitude, longitude);
      load();
      const refresh = setInterval(load, WEATHER_REFRESH_MS);
      this.destroyRef.onDestroy(() => clearInterval(refresh));
    };
    const approximate = () =>
      this.http.get<GeoJsLocation>(APPROX_LOCATION_URL).subscribe({
        next: ({ latitude, longitude }) => begin(Number(latitude), Number(longitude)),
        error: () => this.appWeather.set(null), // no location at all: show no weather
      });

    const geolocation = this.document.defaultView?.navigator.geolocation;
    if (!geolocation) {
      approximate();
      return;
    }
    geolocation.getCurrentPosition(
      ({ coords }) => begin(coords.latitude, coords.longitude),
      approximate,
      { maximumAge: WEATHER_REFRESH_MS, timeout: 10_000 },
    );
  }

  private loadWeather(latitude: number, longitude: number): void {
    const params = {
      latitude: latitude.toFixed(2),
      longitude: longitude.toFixed(2),
      current: 'temperature_2m',
      temperature_unit: 'celsius',
    };
    this.http.get<OpenMeteoCurrent>(WEATHER_URL, { params }).subscribe({
      next: ({ current }) => this.appWeather.set(Math.round(current.temperature_2m)),
      error: () => undefined, // keep the last known temperature
    });
  }
}

export function formatClockTime(date: Date): string {
  const hours = date.getHours();
  const minutes = String(date.getMinutes()).padStart(2, '0');
  return `${hours % 12 || 12}:${minutes}`;
}

function readStoredFinish(): DeviceFinish {
  try {
    return globalThis.localStorage?.getItem(FINISH_KEY) === 'dark' ? 'dark' : 'light';
  } catch {
    return 'light'; // storage blocked: fall back to the default each visit
  }
}

function storeFinish(finish: DeviceFinish): void {
  try {
    globalThis.localStorage?.setItem(FINISH_KEY, finish);
  } catch {
    // Private windows and blocked storage: the choice lasts until reload.
  }
}

/** The home screen is the root path, whatever query or fragment follows. */
export function isHome(url: string): boolean {
  return url.split(/[?#]/)[0] === '/';
}
