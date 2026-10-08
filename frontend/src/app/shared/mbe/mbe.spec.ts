import { TestBed } from '@angular/core/testing';

import { Mbe } from './mbe';

function activeClip(host: HTMLElement): string | null {
  return host.querySelector('video.active')?.getAttribute('data-clip') ?? null;
}

describe('Mbe', () => {
  it('shows his state to styles and to screen readers', async () => {
    const fixture = TestBed.createComponent(Mbe);
    fixture.componentRef.setInput('state', 'speaking');
    await fixture.whenStable();
    const host = fixture.nativeElement as HTMLElement;

    expect(host.getAttribute('data-state')).toBe('speaking');
    expect(host.getAttribute('role')).toBe('img');
    expect(host.getAttribute('aria-label')).toBe('Mbe the tortoise, telling a story');
  });

  it('plays a state with the same pose straight away', async () => {
    const fixture = TestBed.createComponent(Mbe);
    await fixture.whenStable();
    fixture.componentRef.setInput('state', 'listening');
    await fixture.whenStable();

    expect(activeClip(fixture.nativeElement)).toBe('listening');
  });

  it('sits down before thinking, and stands up before resting again', async () => {
    const fixture = TestBed.createComponent(Mbe);
    const host = fixture.nativeElement as HTMLElement;
    const end = (clip: string) =>
      host.querySelector(`video[data-clip="${clip}"]`)!.dispatchEvent(new Event('ended'));
    await fixture.whenStable();

    fixture.componentRef.setInput('state', 'thinking');
    await fixture.whenStable();
    expect(activeClip(host)).toBe('sit-down');

    fixture.componentRef.setInput('state', 'speaking'); // arrives mid-transition
    await fixture.whenStable();
    expect(activeClip(host)).toBe('sit-down');

    end('sit-down');
    await fixture.whenStable();
    expect(activeClip(host)).toBe('speaking');

    fixture.componentRef.setInput('state', 'idle');
    await fixture.whenStable();
    expect(activeClip(host)).toBe('stand-up');
    end('stand-up');
    await fixture.whenStable();
    expect(activeClip(host)).toBe('idle');
  });

  it('can arrive seated and stand up into his first state', async () => {
    const fixture = TestBed.createComponent(Mbe);
    fixture.componentRef.setInput('enterFrom', 'seated');
    fixture.componentRef.setInput('state', 'idle');
    await fixture.whenStable();
    const host = fixture.nativeElement as HTMLElement;
    expect(activeClip(host)).toBe('stand-up');

    host.querySelector('video[data-clip="stand-up"]')!.dispatchEvent(new Event('ended'));
    await fixture.whenStable();
    expect(activeClip(host)).toBe('idle');
  });

  it('can arrive standing and sit down to rest on his stool', async () => {
    const fixture = TestBed.createComponent(Mbe);
    fixture.componentRef.setInput('enterFrom', 'standing');
    fixture.componentRef.setInput('state', 'resting');
    await fixture.whenStable();
    const host = fixture.nativeElement as HTMLElement;
    expect(activeClip(host)).toBe('sit-down');

    host.querySelector('video[data-clip="sit-down"]')!.dispatchEvent(new Event('ended'));
    await fixture.whenStable();
    expect(activeClip(host)).toBeNull();
    expect(host.querySelector('img.rest.active')).toBeTruthy();
    expect(host.getAttribute('aria-label')).toBe('Mbe the tortoise, resting on his stool');
  });

  it('slows his loops but never his transitions', async () => {
    const fixture = TestBed.createComponent(Mbe);
    fixture.componentRef.setInput('speed', 0.65);
    await fixture.whenStable();
    const video = (clip: string) =>
      (fixture.nativeElement as HTMLElement).querySelector<HTMLVideoElement>(
        `video[data-clip="${clip}"]`,
      )!;

    expect(video('speaking').playbackRate).toBe(0.65);
    expect(video('sit-down').playbackRate).toBe(1);
  });

  it('reports arriving only after sitting down', async () => {
    const fixture = TestBed.createComponent(Mbe);
    let arrived = 0;
    fixture.componentInstance.arrived.subscribe(() => arrived++);
    fixture.componentRef.setInput('enterFrom', 'standing');
    fixture.componentRef.setInput('state', 'speaking');
    await fixture.whenStable();
    expect(arrived).toBe(0);

    (fixture.nativeElement as HTMLElement)
      .querySelector('video[data-clip="sit-down"]')!
      .dispatchEvent(new Event('ended'));
    await fixture.whenStable();
    expect(arrived).toBe(1);
  });
});
