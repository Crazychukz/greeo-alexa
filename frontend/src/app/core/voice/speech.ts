import { Injectable, DOCUMENT, inject, signal } from '@angular/core';
import { firstValueFrom } from 'rxjs';

import { GreeoApi, splitSentences } from '../api';

const VOICE_KEY = 'greeo.voiceOn';
/** Storytellers speak a little slower than an assistant; a tale slower still. */
const RATE = { reply: 0.95, tale: 0.88 };

/**
 * Greeo's voice. Each reply is spoken a sentence at a time: the backend's speech when it
 * has one (Polly), otherwise the browser's own voice (the backend answers 204, the
 * default). Speaking again, or cancel(), stops whatever is playing.
 */
@Injectable({ providedIn: 'root' })
export class Speech {
  private readonly api = inject(GreeoApi);
  private readonly window = inject(DOCUMENT).defaultView;
  /** Bumped on every speak/cancel, so an older reply never keeps talking over a new one. */
  private generation = 0;
  private audio: HTMLAudioElement | null = null;

  /** True while Greeo is talking; Mbe speaks while this is on. */
  readonly speaking = signal(false);
  /** The listener can mute Greeo; remembered for the tab. */
  readonly enabled = signal(readEnabled());

  setEnabled(on: boolean): void {
    this.enabled.set(on);
    try {
      globalThis.sessionStorage?.setItem(VOICE_KEY, on ? '1' : '0');
    } catch {
      // Storage blocked: the choice lasts until reload.
    }
    if (!on) {
      this.cancel();
    }
  }

  /**
   * Say a reply. `voice` is the storyteller voice of a tale (voice_style), if any.
   * `onLastSentence` runs as the final sentence begins: the moment to fetch what comes
   * next, so it is ready when the words end. Resolves true if the reply was said to the
   * end, false if something interrupted it. With the voice off, it waits a reading time.
   */
  async speak(text: string, voice?: string, onLastSentence?: () => void): Promise<boolean> {
    this.cancel();
    const generation = this.generation;
    const sentences = splitSentences(text);
    if (!sentences.length) {
      onLastSentence?.();
      return true;
    }
    if (!this.enabled()) {
      return this.readSilently(sentences, generation, onLastSentence);
    }
    const rate = voice ? RATE.tale : RATE.reply;
    this.speaking.set(true);
    try {
      // Ask the backend first; if it has no speech, use the browser for the whole reply.
      let next = this.fetchAudio(sentences[0], voice);
      for (let index = 0; index < sentences.length; index++) {
        const audio = await next;
        if (generation !== this.generation) {
          return false;
        }
        if (audio === null) {
          await this.speakInBrowser(sentences.slice(index), rate, generation, onLastSentence);
          return generation === this.generation;
        }
        const last = index === sentences.length - 1;
        if (last) {
          onLastSentence?.();
        }
        // Fetch the next sentence while this one plays.
        next = last ? Promise.resolve(null) : this.fetchAudio(sentences[index + 1], voice);
        await this.play(audio, generation);
      }
      return generation === this.generation;
    } catch {
      return generation === this.generation; // speech is a bonus: the words are on screen
    } finally {
      if (generation === this.generation) {
        this.speaking.set(false);
      }
    }
  }

  /** Stop talking now (the listener started speaking, sent something, or muted). */
  cancel(): void {
    this.generation++;
    this.audio?.pause();
    this.audio = null;
    this.window?.speechSynthesis?.cancel();
    this.speaking.set(false);
  }

  private async fetchAudio(sentence: string, voice?: string): Promise<Blob | null> {
    try {
      const result = await firstValueFrom(this.api.speech({ text: sentence.slice(0, 600), voice }));
      return result?.audio ?? null;
    } catch {
      return null; // backend speech failed: fall back to the browser
    }
  }

  private play(blob: Blob, generation: number): Promise<void> {
    return new Promise((resolve) => {
      if (generation !== this.generation) {
        resolve();
        return;
      }
      const url = URL.createObjectURL(blob);
      const audio = new Audio(url);
      this.audio = audio;
      const done = () => {
        URL.revokeObjectURL(url);
        resolve();
      };
      audio.onended = done;
      audio.onerror = done;
      audio.play().catch(done);
    });
  }

  /** Voice off: give the listener time to read, about 2.6 words a second. */
  private readSilently(
    sentences: string[],
    generation: number,
    onLastSentence?: () => void,
  ): Promise<boolean> {
    const words = sentences.join(' ').split(/\s+/).length;
    const total = Math.max(2500, (words / 2.6) * 1000);
    return new Promise((resolve) => {
      setTimeout(
        () => {
          if (generation === this.generation) {
            onLastSentence?.();
          }
        },
        Math.max(0, total - 3000),
      );
      setTimeout(() => resolve(generation === this.generation), total);
    });
  }

  private speakInBrowser(
    sentences: string[],
    rate: number,
    generation: number,
    onLastSentence?: () => void,
  ): Promise<void> {
    const synth = this.window?.speechSynthesis;
    if (!synth || typeof SpeechSynthesisUtterance === 'undefined') {
      onLastSentence?.();
      return Promise.resolve();
    }
    const voice = pickVoice(synth.getVoices());
    return new Promise((resolve) => {
      sentences.forEach((sentence, index) => {
        const utterance = new SpeechSynthesisUtterance(sentence);
        utterance.rate = rate;
        if (voice) {
          utterance.voice = voice;
        }
        if (index === sentences.length - 1) {
          utterance.onstart = () => {
            if (generation === this.generation) {
              onLastSentence?.();
            }
          };
          utterance.onend = () => resolve();
          utterance.onerror = () => resolve();
        }
        if (generation === this.generation) {
          synth.speak(utterance);
        }
      });
      if (!sentences.length) {
        resolve();
      }
    });
  }
}

/** A natural English voice if the system has one; otherwise the browser's default. */
function pickVoice(voices: SpeechSynthesisVoice[]): SpeechSynthesisVoice | undefined {
  const english = voices.filter((voice) => voice.lang.startsWith('en'));
  const preferred = [
    'Daniel',
    'Google UK English Male',
    'Samantha',
    'Karen',
    'Moira',
    'Google US English',
  ];
  return (
    preferred.map((name) => english.find((voice) => voice.name.includes(name))).find(Boolean) ??
    english.find((voice) => voice.localService) ??
    english[0]
  );
}

function readEnabled(): boolean {
  try {
    return globalThis.sessionStorage?.getItem(VOICE_KEY) !== '0';
  } catch {
    return true;
  }
}
