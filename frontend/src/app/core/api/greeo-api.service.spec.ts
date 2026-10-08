import { provideHttpClient, withInterceptors, HttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { firstValueFrom } from 'rxjs';

import { GreeoApi, GreeoApiError } from './greeo-api.service';
import { TurnResult, hasDisplay } from './greeo-api.types';
import { identityInterceptor } from './identity.interceptor';
import { ListenerSession } from './listener-session';
import { splitSentences } from './sentences';

const BASE = '/api/simulator';

// A real reply captured from the backend (docs/FRONTEND_API.md), trimmed.
const TALE_TURN: TurnResult = {
  spoken: 'Listen. In Veloria, the Pell River ran wide and cold.',
  display: {
    tool: 'tell_tale',
    resource_uri: 'ui://greeo/tale',
    structured: {
      spoken: 'Listen. In Veloria, the Pell River ran wide and cold.',
      next_options: ['continue', 'the facts'],
      story_id: 'st_c07675295ace',
      title: 'SYNTHETIC EVENT: The Lantern Footbridge of Veloria',
      progress: { current: 'tale', steps: [{ key: 'tale', label: 'TALE', state: 'current' }] },
      beat: 1,
      beats_total: 3,
      has_more: true,
      tone_served: 'balanced',
      voice_style: 'moonlight_elder',
      voice_name: 'Moonlight Elder',
      text: 'Listen. In Veloria, the Pell River ran wide and cold.',
      proverbs_used: [],
    },
    is_error: false,
  },
  tool_trace: [{ tool: 'tell_tale', args: { beat: 1 }, ms: 64, ok: true }],
  host_mode: 'mock',
};

describe('GreeoApi', () => {
  let api: GreeoApi;
  let session: ListenerSession;
  let http: HttpTestingController;

  beforeEach(() => {
    sessionStorage.clear();
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(withInterceptors([identityInterceptor])),
        provideHttpClientTesting(),
      ],
    });
    api = TestBed.inject(GreeoApi);
    session = TestBed.inject(ListenerSession);
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => http.verify());

  it('sends a turn with the session id and returns the typed reply', async () => {
    const reply = firstValueFrom(api.turn('tell me about the footbridge'));

    const request = http.expectOne(`${BASE}/turn`);
    expect(request.request.method).toBe('POST');
    expect(request.request.body).toEqual({
      session_id: session.sessionId(),
      text: 'tell me about the footbridge',
    });
    request.flush(TALE_TURN);

    const turn = await reply;
    expect(hasDisplay(turn) && turn.display.resource_uri).toBe('ui://greeo/tale');
  });

  it('identifies the listener on API calls only', () => {
    api.turn('hello').subscribe();
    expect(http.expectOne(`${BASE}/turn`).request.headers.keys()).toEqual([]);

    session.signIn({ kind: 'token', token: ' greeo_abc ' });
    api.turn('hello').subscribe();
    expect(http.expectOne(`${BASE}/turn`).request.headers.get('Authorization')).toBe(
      'Bearer greeo_abc',
    );

    session.signIn({ kind: 'dev', name: 'ada' });
    api.turn('hello').subscribe();
    const dev = http.expectOne(`${BASE}/turn`).request.headers;
    expect(dev.get('X-Greeo-User')).toBe('ada');
    expect(dev.has('Authorization')).toBe(false);

    TestBed.inject(HttpClient).get('https://elsewhere.test/x').subscribe();
    expect(http.expectOne('https://elsewhere.test/x').request.headers.has('X-Greeo-User')).toBe(
      false,
    );
  });

  it('resets the old conversation and starts a new one', () => {
    const before = session.sessionId();

    api.reset().subscribe();

    expect(http.expectOne(`${BASE}/reset`).request.body).toEqual({ session_id: before });
    expect(session.sessionId()).not.toBe(before);
    expect(session.sessionId()).toMatch(/^[A-Za-z0-9_-]{1,64}$/);
  });

  it('fetches each card once, but retries a card that failed', async () => {
    const first = firstValueFrom(api.card('ui://greeo/facts'));
    const second = firstValueFrom(api.card('ui://greeo/facts'));
    http
      .expectOne(`${BASE}/resource?uri=ui://greeo/facts`)
      .flush({ uri: 'ui://greeo/facts', mime_type: 'text/html;profile=mcp-app', text: '<p>' });
    expect((await first).text).toBe('<p>');
    expect((await second).text).toBe('<p>');

    const failed = firstValueFrom(api.card('ui://greeo/tale'));
    http
      .expectOne(`${BASE}/resource?uri=ui://greeo/tale`)
      .flush({ detail: 'missing' }, { status: 404, statusText: 'Not Found' });
    await expect(failed).rejects.toMatchObject({ kind: 'not_found' });
    api.card('ui://greeo/tale').subscribe();
    http.expectOne(`${BASE}/resource?uri=ui://greeo/tale`);
  });

  it('returns null speech when the backend has none, so the browser speaks', async () => {
    const none = firstValueFrom(api.speech({ text: 'Listen.' }));
    http.expectOne(`${BASE}/tts`).flush(null, { status: 204, statusText: 'No Content' });
    expect(await none).toBeNull();

    const audio = firstValueFrom(api.speech({ text: 'Listen.', voice: 'moonlight_elder' }));
    const request = http.expectOne(`${BASE}/tts`);
    expect(request.request.body).toEqual({ text: 'Listen.', voice: 'moonlight_elder' });
    request.flush(new Blob(['mp3'], { type: 'audio/mpeg' }), {
      headers: { 'X-Greeo-Speech-Cache': 'hit' },
    });
    expect(await audio).toMatchObject({ cached: true });
  });

  it('turns transport failures into errors the UI can act on', async () => {
    const offline = firstValueFrom(api.turn('hello'));
    http.expectOne(`${BASE}/turn`).error(new ProgressEvent('error'), { status: 0 });
    await expect(offline).rejects.toMatchObject({ kind: 'offline' });

    const invalid = firstValueFrom(api.turn(''));
    http
      .expectOne(`${BASE}/turn`)
      .flush({ text: ['This field may not be blank.'] }, { status: 400, statusText: 'Bad' });
    const error = await invalid.catch((e: GreeoApiError) => e);
    expect(error).toBeInstanceOf(GreeoApiError);
    expect((error as GreeoApiError).fieldErrors).toEqual({
      text: ['This field may not be blank.'],
    });
  });
});

describe('ListenerSession', () => {
  beforeEach(() => sessionStorage.clear());

  it('remembers the listener for the tab, and falls back to guest', () => {
    TestBed.inject(ListenerSession).signIn({ kind: 'dev', name: 'bola' });
    expect(JSON.parse(sessionStorage.getItem('greeo.listener')!)).toEqual({
      kind: 'dev',
      name: 'bola',
    });

    TestBed.inject(ListenerSession).signIn({ kind: 'token', token: '   ' });
    expect(TestBed.inject(ListenerSession).isGuest()).toBe(true);
  });
});

describe('splitSentences', () => {
  it('splits on sentence ends only', () => {
    expect(splitSentences('Listen. It cost $16.5bn! Was it worth it?  Yes')).toEqual([
      'Listen.',
      'It cost $16.5bn!',
      'Was it worth it?',
      'Yes',
    ]);
  });
});
