import { DestroyRef, Injectable, computed, inject, signal } from '@angular/core';
import { Observable, firstValueFrom } from 'rxjs';

import { GreeoApi, GreeoApiError, TurnResult, hasDisplay } from '../api';
import { Microphone } from '../voice/microphone';
import { Speech } from '../voice/speech';
import type { MbeState } from '../../shared/mbe/mbe';

/** One thing the listener said, and Greeo's reply once it arrives. */
export interface Exchange {
  said: string;
  reply: TurnResult | null;
  /** Set when the reply could not be fetched at all (offline, server error). */
  failed: boolean;
  /** Greeo carried on by itself (the next beat of a tale), not the listener. */
  auto?: boolean;
}

/** What Greeo says when the web service itself cannot be reached. */
export const OFFLINE_REPLY = "I can't reach Greeo right now. Please try again in a moment.";

/** What the tale asks for next, said on the listener's behalf while Greeo keeps telling. */
const NEXT_BEAT = 'continue';
const CLOSING = 'the moral';
/** Ways of asking the tale to go on, which may play a part already fetched. */
const CONTINUE_WORDS = new Set([
  'continue',
  'go on',
  'keep going',
  'carry on',
  'what happened next',
]);

/**
 * The conversation with Greeo. It belongs to the listening screen (provided by it, not
 * app-wide), so leaving that screen ends it: speech stops and late replies are dropped.
 * Other pages start one by navigating with an opening (see opening.ts). Pages read
 * signals; only say(), pause() and startOver() change it.
 *
 * A tale tells itself, like a storyteller by the fire: when a beat has more to come, the
 * next one is fetched as the last sentence begins and played when the words end; after
 * the final beat comes the closing reflection, then Greeo waits. Anything the listener
 * does (types, speaks, taps a chip, pauses) interrupts it.
 *
 * Mbe follows: thinking while the listener waits for a reply, speaking while Greeo
 * talks (and in the short pause between beats), listening otherwise.
 */
@Injectable()
export class Conversation {
  private readonly api = inject(GreeoApi);
  private readonly speech = inject(Speech);
  private readonly microphone = inject(Microphone);

  constructor() {
    // The listening screen is gone: stop talking, and drop any reply still on its way.
    inject(DestroyRef).onDestroy(() => {
      this.held = null;
      this.pause();
    });
  }

  private readonly exchangeList = signal<Exchange[]>([]);
  /** Bumped by anything the listener does, so an older telling never carries on. */
  private telling = 0;
  /**
   * The next part, fetched early and then interrupted before it played. The server
   * already counts it as told, so "continue" must play this, not ask for a new one.
   */
  private held: { request: string; reply: Promise<TurnResult> } | null = null;
  /** The next part being fetched while the current one finishes. */
  private upcoming: { request: string; reply: Promise<TurnResult> } | null = null;
  /** True while a tale is telling itself, between and during its beats. */
  readonly isTelling = signal(false);
  /** True while Greeo's voice is playing. */
  readonly speaking = this.speech.speaking;

  readonly exchanges = this.exchangeList.asReadonly();
  /** What the listener said (Greeo's own continuations left out). */
  readonly said = computed(() => this.exchangeList().filter((e) => !e.auto));
  /** Waiting for the listener's own request (Greeo's own continuations never block them). */
  readonly busy = computed(() => this.exchangeList().some((e) => !e.reply && !e.failed && !e.auto));
  readonly started = computed(() => this.exchangeList().length > 0);
  readonly latest = computed(() => this.exchangeList().at(-1) ?? null);
  /** The latest reply that came back, even while a newer one is still on its way. */
  readonly lastReply = computed(
    () => [...this.exchangeList()].reverse().find((e) => e.reply)?.reply ?? null,
  );
  /** Greeo's words to show and speak: the latest reply, or the offline message. */
  readonly spoken = computed(() => {
    const latest = this.latest();
    if (latest?.failed && !latest.auto) {
      return OFFLINE_REPLY;
    }
    return this.lastReply()?.spoken ?? '';
  });
  /** What to show beside the words: the latest tool result, if a tool answered. */
  readonly display = computed(() => {
    const reply = this.lastReply();
    return reply && hasDisplay(reply) ? reply.display : null;
  });
  /** Suggestion chips: the latest result's next options (hidden while a tale tells itself). */
  readonly options = computed(() =>
    this.isTelling() ? [] : (this.display()?.structured.next_options ?? []),
  );
  readonly mbeState = computed<MbeState>(() => {
    if (this.isTelling() || this.speaking()) {
      return 'speaking';
    }
    if (this.busy()) {
      return 'thinking';
    }
    return this.started() || this.microphone.listening() ? 'listening' : 'idle';
  });

  /**
   * Send what the listener said (or a chip's label). Interrupts any telling. A storyId
   * means they tapped that story on screen: the text is what they are shown saying.
   */
  say(text: string, storyId?: string): void {
    const said = text.trim().slice(0, 500);
    if (!said) {
      return;
    }
    this.pause();
    if (this.busy()) {
      return; // one question at a time
    }
    const exchange: Exchange = { said, reply: null, failed: false };
    this.add(exchange);
    const held = this.held;
    this.held = null;
    const request =
      held && !storyId && CONTINUE_WORDS.has(said.toLowerCase().replace(/[.!?]+$/, ''))
        ? fromPromise(held.reply) // play the part that was fetched but never heard
        : this.api.turn(said, storyId);
    void this.answer(exchange, request, this.telling);
  }

  /** Stop talking and stop the tale where it is; "continue" picks it up again. */
  pause(): void {
    if (this.upcoming && this.isTelling()) {
      this.held = this.upcoming; // fetched, not yet heard: keep it for "continue"
    }
    this.upcoming = null;
    this.telling++;
    this.isTelling.set(false);
    this.speech.cancel();
  }

  /** Forget this conversation here and on the server; saved stories are kept. */
  startOver(): void {
    this.pause();
    this.held = null;
    this.exchangeList.set([]);
    this.api.reset().subscribe({ error: () => undefined });
  }

  /** Settle an exchange with its reply, say it, and keep a tale going if it should. */
  private async answer(
    exchange: Exchange,
    request: Observable<TurnResult>,
    telling: number,
  ): Promise<void> {
    let reply: TurnResult;
    try {
      reply = await firstValueFrom(request);
    } catch (error) {
      if (!(error instanceof GreeoApiError)) {
        console.error(error);
      }
      this.settle(exchange, { failed: true });
      if (telling === this.telling && !exchange.auto) {
        void this.speech.speak(OFFLINE_REPLY);
      }
      this.isTelling.set(false);
      return;
    }
    if (telling !== this.telling) {
      // The listener moved on while this was on its way: drop it if Greeo asked for it.
      if (exchange.auto) {
        this.exchangeList.update((list) => list.filter((item) => item !== exchange));
      } else {
        this.settle(exchange, { reply });
      }
      return;
    }
    this.settle(exchange, { reply });
    const next = whatComesNext(reply);
    this.isTelling.set(next !== null);
    this.upcoming = null;
    const finished = await this.speech.speak(reply.spoken, voiceOf(reply), () => {
      // The last sentence has begun: fetch the next part now, so there is no dead air.
      if (next && telling === this.telling && !this.upcoming) {
        const ahead = firstValueFrom(this.ownTurn(next, reply));
        ahead.catch(() => undefined);
        this.upcoming = { request: next, reply: ahead };
      }
    });
    if (!finished || telling !== this.telling || !next) {
      if (telling === this.telling) {
        this.isTelling.set(false);
      }
      return;
    }
    const auto: Exchange = { said: next, reply: null, failed: false, auto: true };
    this.add(auto);
    const pending = this.takeUpcoming()?.reply ?? firstValueFrom(this.ownTurn(next, reply));
    await this.answer(auto, fromPromise(pending), telling);
  }

  /**
   * Greeo carrying on with its own tale. It names the story and what comes next, so the
   * server tells it directly: no model has to work out what "continue" meant.
   */
  private ownTurn(next: string, reply: TurnResult): Observable<TurnResult> {
    const storyId = hasDisplay(reply)
      ? (reply.display.structured as { story_id?: string }).story_id
      : undefined;
    return this.api.turn(next, storyId, next === NEXT_BEAT ? 'next_beat' : 'closing');
  }

  /** The part fetched during the last sentence, if any; set from the speech callback. */
  private takeUpcoming(): { request: string; reply: Promise<TurnResult> } | null {
    const upcoming = this.upcoming;
    this.upcoming = null;
    return upcoming;
  }

  private add(exchange: Exchange): void {
    this.exchangeList.update((list) => [...list, exchange]);
  }

  private settle(exchange: Exchange, outcome: Partial<Exchange>): void {
    this.exchangeList.update((list) =>
      list.map((item) => (item === exchange ? Object.assign(item, outcome) : item)),
    );
  }
}

/**
 * What Greeo says next on its own: the next beat while the tale has more, the closing
 * reflection after the last beat, and nothing after that.
 */
export function whatComesNext(reply: TurnResult): string | null {
  if (!hasDisplay(reply) || reply.display.is_error || reply.display.tool !== 'tell_tale') {
    return null;
  }
  const structured = reply.display.structured as { has_more?: boolean };
  return structured.has_more ? NEXT_BEAT : CLOSING;
}

/** A tale's storyteller voice, so speech can be paced for it; none for other replies. */
function voiceOf(reply: TurnResult): string | undefined {
  if (!hasDisplay(reply)) {
    return undefined;
  }
  const structured = reply.display.structured as { voice_style?: string };
  return structured.voice_style || undefined;
}

function fromPromise<T>(promise: Promise<T>): Observable<T> {
  return new Observable<T>((subscriber) => {
    promise.then(
      (value) => {
        subscriber.next(value);
        subscriber.complete();
      },
      (error: unknown) => subscriber.error(error),
    );
  });
}
