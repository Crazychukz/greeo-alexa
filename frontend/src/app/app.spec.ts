import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';

import { App, formatClockTime, isHome } from './app';
import { routes } from './app.routes';

describe('App', () => {
  beforeEach(() => {
    TestBed.configureTestingModule({
      imports: [App],
      providers: [provideRouter(routes), provideHttpClient(), provideHttpClientTesting()],
    });
  });

  it('renders every page on the device screen', async () => {
    const fixture = TestBed.createComponent(App);
    const harness = await RouterTestingHarness.create();
    await harness.navigateByUrl('/');
    fixture.detectChanges();
    await fixture.whenStable();
    const shell = fixture.nativeElement as HTMLElement;

    expect(shell.querySelector('.device .display router-outlet')).toBeTruthy();
    expect(shell.textContent).toContain('Full screen');
  });

  it('shows the home screen at / and sends unknown paths home', async () => {
    const harness = await RouterTestingHarness.create();

    await harness.navigateByUrl('/');
    expect(harness.routeNativeElement?.querySelector('.home')).toBeTruthy();

    await harness.navigateByUrl('/no-such-page');
    expect(harness.routeNativeElement?.querySelector('.home')).toBeTruthy();
  });

  it('formats the device clock like 10:10', () => {
    expect(formatClockTime(new Date(2026, 9, 6, 10, 10))).toBe('10:10');
    expect(formatClockTime(new Date(2026, 9, 6, 0, 5))).toBe('12:05');
    expect(formatClockTime(new Date(2026, 9, 6, 12, 0))).toBe('12:00');
    expect(formatClockTime(new Date(2026, 9, 6, 21, 47))).toBe('9:47');
  });

  it('toggles a dark device on a light page and a light device on a dark page', async () => {
    localStorage.clear();
    const fixture = TestBed.createComponent(App);
    fixture.detectChanges();
    await fixture.whenStable();
    const html = document.documentElement;
    const toggle = (fixture.nativeElement as HTMLElement).querySelector<HTMLButtonElement>(
      '[role=switch]',
    )!;
    expect(html.dataset['device']).toBe('light');
    expect(toggle.getAttribute('aria-checked')).toBe('false');

    toggle.click();
    fixture.detectChanges();
    await fixture.whenStable();
    expect(html.dataset['device']).toBe('dark');
    expect(localStorage.getItem('greeo.deviceFinish')).toBe('dark');
    expect(toggle.getAttribute('aria-checked')).toBe('true');
  });

  it('knows the home screen whatever query follows', () => {
    expect(isHome('/')).toBe(true);
    expect(isHome('/?story=st_1')).toBe(true);
    expect(isHome('/listen')).toBe(false);
  });
});
