import { ChangeDetectionStrategy, Component, inject, input, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';

import { Conversation } from '../../core/conversation/conversation';
import { openListen } from '../../core/conversation/opening';
import { Microphone } from '../../core/voice/microphone';

/**
 * How the listener talks to Greeo: type, or push to talk. On the listening screen it
 * talks to that screen's conversation; on any other page there is none, so sending opens
 * the listening screen with the words (opensConversation).
 */
@Component({
  selector: 'greeo-ask-bar',
  imports: [FormsModule],
  templateUrl: './ask-bar.html',
  styleUrl: './ask-bar.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AskBar {
  readonly opensConversation = input(false);
  readonly placeholder = input('Ask Greeo, or say "what\'s happening today?"');

  /** The listening screen's conversation; none on other pages. */
  protected readonly conversation = inject(Conversation, { optional: true });
  protected readonly microphone = inject(Microphone);
  private readonly router = inject(Router);
  protected readonly text = signal('');

  protected send(): void {
    const text = this.text();
    if (!text.trim() || this.conversation?.busy()) {
      return;
    }
    this.text.set('');
    this.deliver(text);
  }

  /** Push to talk: press to listen, press again (or just stop speaking) to send. */
  protected toggleMic(): void {
    if (this.microphone.listening()) {
      this.microphone.stop();
      return;
    }
    this.conversation?.pause(); // Greeo stops telling when the listener starts to speak
    this.microphone.start((words) => this.deliver(words));
  }

  private deliver(words: string): void {
    if (this.conversation && !this.opensConversation()) {
      this.conversation.say(words);
    } else {
      void openListen(this.router, { text: words });
    }
  }
}
