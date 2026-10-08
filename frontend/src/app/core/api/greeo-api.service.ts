import { HttpClient, HttpErrorResponse, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable, catchError, map, shareReplay, throwError } from 'rxjs';

import { GREEO_API_BASE } from './api-config';
import {
  CardResource,
  CardUri,
  FollowUp,
  ResetResult,
  SpeechAudio,
  StoryShelf,
  TtsRequest,
  TurnRequest,
  TurnResult,
} from './greeo-api.types';
import { ListenerSession } from './listener-session';

/**
 * Why a call failed, in terms the UI can act on.
 *
 * Conversational problems (no story found, a revoked token, too many requests) are
 * NOT errors: the backend answers 200 with something to say. These are for the cases
 * the contract treats as app or network failures.
 */
export type ApiFailure =
  /** The web service could not be reached: show an offline state. */
  | 'offline'
  /** 400: the app sent something invalid. A bug; never spoken. */
  | 'invalid'
  /** 404 for a card that does not exist. */
  | 'not_found'
  /** Anything else from the server. */
  | 'server';

export class GreeoApiError extends Error {
  constructor(
    readonly kind: ApiFailure,
    readonly status: number,
    /** DRF field errors for a 400, keyed by field. */
    readonly fieldErrors: Record<string, string[]> = {},
  ) {
    super(`Greeo API ${kind} (${status})`);
    this.name = 'GreeoApiError';
  }
}

/** The simulator endpoints from docs/FRONTEND_API.md. */
@Injectable({ providedIn: 'root' })
export class GreeoApi {
  private readonly http = inject(HttpClient);
  private readonly base = inject(GREEO_API_BASE);
  private readonly session = inject(ListenerSession);
  /** Card HTML changes only on redeploy, so each card is fetched once per page load. */
  private readonly cards = new Map<CardUri, Observable<CardResource>>();

  /**
   * One thing the listener said; the reply to speak, show and trace. With a storyId the
   * listener tapped that story on screen, and it is told straight away.
   */
  turn(text: string, storyId?: string, followUp?: FollowUp): Observable<TurnResult> {
    const body: TurnRequest = { session_id: this.session.sessionId(), text };
    if (storyId) {
      body.story_id = storyId;
      if (followUp) {
        body.follow_up = followUp;
      }
    }
    return this.http.post<TurnResult>(`${this.base}/turn`, body).pipe(catchError(toApiError));
  }

  /** The home screen's Demo stories card: demo stories and the count of today's news. */
  stories(): Observable<StoryShelf> {
    return this.http.get<StoryShelf>(`${this.base}/stories`).pipe(catchError(toApiError));
  }

  /** Start over: clears this conversation here and on the server; saves are kept. */
  reset(): Observable<ResetResult> {
    const sessionId = this.session.sessionId();
    this.session.newConversation();
    return this.http
      .post<ResetResult>(`${this.base}/reset`, { session_id: sessionId })
      .pipe(catchError(toApiError));
  }

  /** A card's HTML for a sandboxed iframe, cached for the page's lifetime. */
  card(uri: CardUri): Observable<CardResource> {
    let card = this.cards.get(uri);
    if (!card) {
      card = this.http
        .get<CardResource>(`${this.base}/resource`, { params: new HttpParams().set('uri', uri) })
        .pipe(
          catchError((error) => {
            this.cards.delete(uri); // a failed fetch may succeed next time
            return toApiError(error);
          }),
          shareReplay({ bufferSize: 1, refCount: false }),
        );
      this.cards.set(uri, card);
    }
    return card;
  }

  /**
   * Audio for one sentence, or null when the backend has no speech configured (204):
   * the caller then uses the browser's speechSynthesis.
   */
  speech(request: TtsRequest): Observable<SpeechAudio | null> {
    return this.http
      .post(`${this.base}/tts`, request, { observe: 'response', responseType: 'blob' })
      .pipe(
        map((response) =>
          response.status === 204 || !response.body?.size
            ? null
            : {
                audio: response.body,
                cached: response.headers.get('X-Greeo-Speech-Cache') === 'hit',
              },
        ),
        catchError(toApiError),
      );
  }
}

function toApiError(error: unknown): Observable<never> {
  if (!(error instanceof HttpErrorResponse)) {
    return throwError(() => error);
  }
  if (error.status === 0) {
    return throwError(() => new GreeoApiError('offline', 0));
  }
  if (error.status === 400) {
    const fields = typeof error.error === 'object' && error.error ? error.error : {};
    return throwError(() => new GreeoApiError('invalid', 400, fields));
  }
  if (error.status === 404) {
    return throwError(() => new GreeoApiError('not_found', 404));
  }
  return throwError(() => new GreeoApiError('server', error.status));
}
