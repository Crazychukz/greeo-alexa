import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';

import { TurnResult } from '../api';
import { Speech } from '../voice/speech';
import { Conversation, OFFLINE_REPLY } from './conversation';

/**
 * Stands in for Greeo's voice: no audio, no /tts. Each reply "plays" until finish() is
 * called, so tests can act while Greeo is still talking.
 */
class ScriptedSpeech {
  readonly speaking = signal(false);
  readonly enabled = signal(true);
  readonly said: string[] = [];
  private current: { done: (finished: boolean) => void } | null = null;

  speak(text: string, _voice?: string, onLastSentence?: () => void): Promise<boolean> {
    this.said.push(text);
    this.speaking.set(true);
    onLastSentence?.();
    return new Promise((done) => (this.current = { done }));
  }
  finish(): void {
    this.speaking.set(false);
    this.current?.done(true);
    this.current = null;
  }
  cancel(): void {
    this.speaking.set(false);
    this.current?.done(false);
    this.current = null;
  }
}

function tale(beat: number, total: number): TurnResult {
  const spoken = `SYNTHETIC beat ${beat}.`;
  return {
    spoken,
    display: {
      tool: 'tell_tale',
      resource_uri: 'ui://greeo/tale',
      structured: {
        spoken,
        next_options: ['continue'],
        story_id: 'st_1',
        title: 'SYNTHETIC EVENT',
        progress: { current: 'tale', steps: [] },
        beat,
        beats_total: total,
        has_more: beat < total,
        tone_served: 'balanced',
        voice_style: 'moonlight_elder',
        voice_name: 'Moonlight Elder',
        text: spoken,
        proverbs_used: [],
      },
      is_error: false,
    },
    tool_trace: [{ tool: 'tell_tale', args: { beat }, ms: 5, ok: true }],
    host_mode: 'mock',
  };
}

const CLOSING: TurnResult = {
  spoken: 'SYNTHETIC reflection.',
  display: {
    tool: 'get_moral',
    resource_uri: 'ui://greeo/wisdom',
    structured: {
      spoken: 'SYNTHETIC reflection.',
      next_options: ['the facts'],
      story_id: 'st_1',
      title: 'SYNTHETIC EVENT',
      progress: { current: 'closing', steps: [] },
      closing_kind: 'reflection',
      text: 'SYNTHETIC reflection.',
      proverb_note: '',
      proverbs: [],
    },
    is_error: false,
  },
  tool_trace: [{ tool: 'get_moral', args: {}, ms: 5, ok: true }],
  host_mode: 'mock',
};

const tick = () => new Promise((resolve) => setTimeout(resolve));

describe('Conversation', () => {
  let conversation: Conversation;
  let http: HttpTestingController;
  let speech: ScriptedSpeech;

  beforeEach(() => {
    sessionStorage.clear();
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        { provide: Speech, useClass: ScriptedSpeech },
        Conversation, // the listening screen provides it; here the test does
      ],
    });
    conversation = TestBed.inject(Conversation);
    http = TestBed.inject(HttpTestingController);
    speech = TestBed.inject(Speech) as unknown as ScriptedSpeech;
  });

  afterEach(() => http.verify());

  const reply = (body: TurnResult) => http.expectOne('/api/simulator/turn').flush(body);
  const sentText = () => http.expectOne('/api/simulator/turn').request.body.text as string;

  it('tells a tale by itself, beat after beat, then the closing, then waits', async () => {
    conversation.say('tell me the story');
    expect(conversation.mbeState()).toBe('thinking');
    reply(tale(1, 2));
    await tick();

    // While beat 1 plays, beat 2 is already being fetched (its last sentence began).
    expect(conversation.mbeState()).toBe('speaking');
    expect(conversation.options()).toEqual([]); // no chips mid-tale
    const second = http.expectOne('/api/simulator/turn');
    expect(second.request.body.text).toBe('continue');
    // Greeo names the story and the next part: no model has to interpret "continue".
    expect(second.request.body.story_id).toBe('st_1');
    expect(second.request.body.follow_up).toBe('next_beat');
    second.flush(tale(2, 2));
    speech.finish();
    await tick();
    expect(speech.said).toEqual(['SYNTHETIC beat 1.', 'SYNTHETIC beat 2.']);

    // After the last beat comes the closing reflection, asked for the same way.
    const closing = http.expectOne('/api/simulator/turn');
    expect(closing.request.body.text).toBe('the moral');
    expect(closing.request.body.follow_up).toBe('closing');
  });

  it('plays the closing after the last beat, then stops and offers chips', async () => {
    conversation.say('tell me the story');
    reply(tale(1, 1));
    await tick();
    http.expectOne('/api/simulator/turn').flush(CLOSING);
    speech.finish();
    await tick();
    expect(speech.said.at(-1)).toBe('SYNTHETIC reflection.');

    speech.finish();
    await tick();
    expect(conversation.isTelling()).toBe(false);
    expect(conversation.options()).toEqual(['the facts']);
    expect(conversation.said().map((e) => e.said)).toEqual(['tell me the story']);
  });

  it('stops telling the moment the listener interrupts', async () => {
    conversation.say('tell me the story');
    reply(tale(1, 3));
    await tick();
    const prefetched = http.expectOne('/api/simulator/turn'); // beat 2, fetched early

    conversation.say('the facts'); // the listener interrupts mid-beat
    expect(conversation.isTelling()).toBe(false);
    prefetched.flush(tale(2, 3)); // arrives late: dropped, never spoken
    reply(CLOSING); // the listener's own question is answered
    await tick();

    expect(speech.said).toEqual(['SYNTHETIC beat 1.', 'SYNTHETIC reflection.']);
    expect(conversation.exchanges().some((e) => e.auto)).toBe(false);
  });

  it('pause stops the tale where it is', async () => {
    conversation.say('tell me the story');
    reply(tale(1, 3));
    await tick();
    http.expectOne('/api/simulator/turn').flush(tale(2, 3));

    conversation.pause();
    await tick();

    expect(conversation.isTelling()).toBe(false);
    expect(speech.said).toEqual(['SYNTHETIC beat 1.']);
    expect(conversation.mbeState()).toBe('listening');
  });

  it('says it cannot reach Greeo when offline', async () => {
    conversation.say('today');
    http.expectOne('/api/simulator/turn').error(new ProgressEvent('error'), { status: 0 });
    await tick();

    expect(conversation.spoken()).toBe(OFFLINE_REPLY);
    expect(speech.said.at(-1)).toBe(OFFLINE_REPLY);
    expect(conversation.busy()).toBe(false);
  });

  it('starts over here and on the server', async () => {
    conversation.say('today');
    reply(CLOSING);
    await tick();

    conversation.startOver();

    http.expectOne('/api/simulator/reset').flush({ reset: true });
    expect(conversation.started()).toBe(false);
    expect(conversation.mbeState()).toBe('idle');
  });

  it('keeps a part fetched before a pause, and plays it on continue', async () => {
    conversation.say('tell me the story');
    reply(tale(1, 3));
    await tick();
    const early = http.expectOne('/api/simulator/turn'); // beat 2, fetched as beat 1 ends

    conversation.pause();
    early.flush(tale(2, 3));
    await tick();
    expect(speech.said).toEqual(['SYNTHETIC beat 1.']);

    conversation.say('continue'); // no new request: the held beat 2 plays
    await tick();
    expect(speech.said.at(-1)).toBe('SYNTHETIC beat 2.');
    http.expectOne('/api/simulator/turn'); // and beat 3 is fetched ahead, as usual
  });

  it('drops a held part when the listener asks for something else', async () => {
    conversation.say('tell me the story');
    reply(tale(1, 3));
    await tick();
    http.expectOne('/api/simulator/turn').flush(tale(2, 3));
    conversation.pause();

    conversation.say('the facts');
    expect(sentText()).toBe('the facts');
  });

  it('goes quiet when the listening screen is destroyed, dropping late replies', async () => {
    conversation.say('tell me the story');
    const pending = http.expectOne('/api/simulator/turn');

    TestBed.resetTestingModule(); // destroys the injector that provided the conversation
    pending.flush(tale(1, 3));
    await tick();

    expect(speech.said).toEqual([]);
    expect(conversation.isTelling()).toBe(false);
  });
});
