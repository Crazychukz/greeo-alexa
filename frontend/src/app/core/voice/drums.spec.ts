import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';

import { Conversation } from '../conversation/conversation';
import { Drums, PATTERN } from './drums';

describe('Drums', () => {
  it('keeps a 12/8 bar with the bass on the downbeat', () => {
    expect(PATTERN.length).toBe(12);
    expect(PATTERN[0]).toContain('bass');
  });

  it('stays silent without Web Audio instead of failing the tale', () => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting(), Conversation, Drums],
    });
    const drums = TestBed.inject(Drums);
    drums.start();
    expect(drums.playing).toBe(false);
  });
});
