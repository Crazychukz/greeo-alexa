import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  inject,
  signal,
} from '@angular/core';
import { Router } from '@angular/router';

import { ListenerSession, StoryListing, splitSentences } from '../../core/api';
import { Conversation } from '../../core/conversation/conversation';
import { currentOpening } from '../../core/conversation/opening';
import { Drums } from '../../core/voice/drums';
import { Microphone } from '../../core/voice/microphone';
import { Speech } from '../../core/voice/speech';
import { AskBar } from '../../shared/ask-bar/ask-bar';
import { CardHost } from '../../shared/card-host/card-host';
import { Mbe } from '../../shared/mbe/mbe';

/** The heading above a card is a lead-in, not the card again: about a line and a half. */
const HEADING_WORDS = 16;
export const WELCOME = 'What would you like to hear?';
/** The simulated linked listener: one household, as on a shared kitchen device. */
export const DEMO_LISTENER = 'demo-household';

/**
 * The conversation screen, after the Echo Show's own: what Greeo says and its cards on
 * the left, Mbe on the right with what he is doing beneath him, round buttons top right,
 * and a light bar along the bottom that shows listening, thinking and telling.
 */
@Component({
  selector: 'greeo-listen',
  imports: [AskBar, CardHost, Mbe],
  templateUrl: './listen.html',
  styleUrl: './listen.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
  // The conversation and its drums live and die with this screen: leaving it ends them.
  providers: [Conversation, Drums],
})
export class Listen {
  protected readonly conversation = inject(Conversation);
  protected readonly speech = inject(Speech);
  protected readonly microphone = inject(Microphone);
  protected readonly listener = inject(ListenerSession);

  /** The keyboard: typing is a fallback here, so the ask bar shows only on request. */
  protected readonly typing = signal(false);
  /** The history panel: recent requests, how Greeo answered, and Start over. */
  protected readonly historyOpen = signal(false);

  constructor() {
    inject(Drums); // created with the screen, so tales have their drums
    // Leaving this screen (Home, Back, any link) destroys it, and the conversation with it.
    inject(DestroyRef).onDestroy(() => this.microphone.stop());
    // Started from another page (a tapped story, typed or spoken words): say it first.
    const opening = currentOpening(inject(Router));
    if (opening) {
      this.conversation.say(opening.text, opening.storyId);
    }
  }

  /** Stories to pick from, when the result is a briefing, a search or saved stories. */
  protected readonly stories = computed<StoryListing[]>(() => {
    const structured = this.conversation.display()?.structured;
    return structured && 'stories' in structured ? (structured.stories as StoryListing[]) : [];
  });

  /** What Greeo says, in large type: in full, or as a short lead-in when a card follows. */
  protected readonly heading = computed(() =>
    headingFor(
      this.conversation.spoken(),
      !!this.conversation.display()?.resource_uri,
      this.stories().length > 0,
    ),
  );

  /** Things to ask next, less any story already shown as a tile. */
  protected readonly options = computed(() => {
    const titles = new Set(this.stories().map((story) => story.title));
    return this.conversation.options().filter((option) => !titles.has(option));
  });

  /** One line under Mbe saying what he is doing. */
  protected readonly status = computed(() => {
    if (this.microphone.listening()) {
      return 'Listening…';
    }
    if (this.conversation.busy()) {
      return 'Let me think…';
    }
    if (this.conversation.isTelling()) {
      const structured = this.conversation.display()?.structured as
        | { beat?: number; beats_total?: number }
        | undefined;
      return structured?.beat && structured.beats_total
        ? `Telling · part ${structured.beat} of ${structured.beats_total}`
        : 'Telling…';
    }
    return this.conversation.speaking() ? 'Speaking…' : 'Tap the mic, or ask away';
  });

  /** The last few requests, newest last. */
  protected readonly recent = computed(() => this.conversation.said().slice(-8));

  /** Push to talk, as in the ask bar: Greeo stops telling when the listener speaks. */
  protected toggleMic(): void {
    if (this.microphone.listening()) {
      this.microphone.stop();
      return;
    }
    this.conversation.pause();
    this.microphone.start((words) => this.conversation.say(words));
  }

  /**
   * Simulated account linking: on Alexa+ a listener links Greeo in the Alexa app, and
   * Greeo then knows them across sessions. Here a development identity stands in (the
   * backend honours it only with DEBUG on), so saves and "where you stopped" work.
   */
  protected linkAccount(): void {
    this.listener.signIn({ kind: 'dev', name: DEMO_LISTENER });
  }

  protected unlinkAccount(): void {
    this.listener.signOut();
  }

  protected startOver(): void {
    this.historyOpen.set(false);
    this.conversation.startOver();
  }
}

/**
 * The whole reply when nothing else is on screen. Above a card, its first sentence, cut
 * to a line or so. Above story tiles, the intro and the question, not the titles again.
 */
export function headingFor(spoken: string, hasCard: boolean, hasList = false): string {
  if (!spoken) {
    return WELCOME;
  }
  if (hasList) {
    const intro = spoken.split(':')[0].trim();
    const question = splitSentences(spoken).at(-1) ?? '';
    return question.endsWith('?') && question !== intro ? `${intro}. ${question}` : `${intro}.`;
  }
  if (!hasCard) {
    return spoken;
  }
  const first = splitSentences(spoken)[0] ?? spoken;
  const words = first.split(/\s+/);
  return words.length > HEADING_WORDS ? words.slice(0, HEADING_WORDS).join(' ') + '…' : first;
}
