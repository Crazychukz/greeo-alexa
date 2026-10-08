import { Component } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { Router, provideRouter } from '@angular/router';

import { Opening, currentOpening, openListen } from './opening';

/** Records the opening it found while its route was activated, as Listen does. */
@Component({ template: '' })
class Receiver {
  static seen: Opening | null = null;
  constructor() {
    Receiver.seen = currentOpening(TestBed.inject(Router));
  }
}

describe('openings', () => {
  beforeEach(() => {
    Receiver.seen = null;
    TestBed.configureTestingModule({
      providers: [provideRouter([{ path: 'listen', component: Receiver }])],
    });
  });

  it('carries a tapped story to the listening screen', async () => {
    const router = TestBed.inject(Router);
    const { RouterTestingHarness } = await import('@angular/router/testing');
    const harness = await RouterTestingHarness.create();

    await harness.navigateByUrl('/'); // a starting point
    await openListen(router, { text: 'Tell me SYNTHETIC', storyId: 'st_1' });

    expect(Receiver.seen).toEqual({ text: 'Tell me SYNTHETIC', storyId: 'st_1' });
  });

  it('finds no opening on a plain visit', async () => {
    const { RouterTestingHarness } = await import('@angular/router/testing');
    const harness = await RouterTestingHarness.create();

    await harness.navigateByUrl('/listen');

    expect(Receiver.seen).toBeNull();
  });
});
