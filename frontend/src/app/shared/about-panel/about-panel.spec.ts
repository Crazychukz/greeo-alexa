import { TestBed } from '@angular/core/testing';

import { AboutPanel, SECTIONS } from './about-panel';

describe('AboutPanel', () => {
  async function open() {
    const fixture = TestBed.createComponent(AboutPanel);
    fixture.detectChanges();
    await fixture.whenStable();
    return { fixture, element: fixture.nativeElement as HTMLElement };
  }

  it('opens on the inspiration, and switches pages from the pills', async () => {
    const { fixture, element } = await open();
    const titles = () => [...element.querySelectorAll('[role=tabpanel] h3')].map((h) => h.textContent);
    expect(titles()).toEqual(SECTIONS[0].tiles.map((t) => t.title));

    element.querySelectorAll<HTMLButtonElement>('[role=tab]')[2].click();
    fixture.detectChanges();
    await fixture.whenStable();
    expect(titles()).toEqual(SECTIONS[2].tiles.map((t) => t.title));
  });

  it('closes from the close button, Escape and the backdrop', async () => {
    const { fixture, element } = await open();
    let closed = 0;
    fixture.componentInstance.closed.subscribe(() => closed++);

    element.querySelector<HTMLButtonElement>('[aria-label=Close]')!.click();
    element.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
    element.querySelector<HTMLElement>('.scrim')!.click();
    expect(closed).toBe(3);
  });
});
