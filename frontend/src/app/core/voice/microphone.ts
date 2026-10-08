import { Injectable, DOCUMENT, inject, signal } from '@angular/core';

/** The parts of the Web Speech API recognition object used here (not in TypeScript's DOM types). */
interface Recognition {
  lang: string;
  interimResults: boolean;
  continuous: boolean;
  onresult:
    | ((event: {
        results: ArrayLike<ArrayLike<{ transcript: string }> & { isFinal: boolean }>;
      }) => void)
    | null;
  onend: (() => void) | null;
  onerror: ((event: { error: string }) => void) | null;
  start(): void;
  stop(): void;
  abort(): void;
}
type RecognitionConstructor = new () => Recognition;

/**
 * Push-to-talk speech recognition from the browser (Chrome, Edge and Safari support it).
 * The browser asks for microphone permission the first time. Heard words appear live in
 * `heard`; when the listener stops speaking, the final words go to `onFinal`.
 */
@Injectable({ providedIn: 'root' })
export class Microphone {
  private readonly window = inject(DOCUMENT).defaultView as
    | (Window & {
        SpeechRecognition?: RecognitionConstructor;
        webkitSpeechRecognition?: RecognitionConstructor;
      })
    | null;
  private recognition: Recognition | null = null;

  readonly supported = !!(this.window?.SpeechRecognition ?? this.window?.webkitSpeechRecognition);
  /** True while the microphone is open. */
  readonly listening = signal(false);
  /** Words heard so far in this turn, for live display. */
  readonly heard = signal('');
  /** Why listening stopped, when it was a problem the listener should know about. */
  readonly problem = signal<string | null>(null);

  start(onFinal: (words: string) => void): void {
    const Recognizer = this.window?.SpeechRecognition ?? this.window?.webkitSpeechRecognition;
    if (!Recognizer || this.listening()) {
      return;
    }
    const recognition = new Recognizer();
    recognition.lang = this.window?.navigator.language || 'en-GB';
    recognition.interimResults = true;
    recognition.continuous = false; // one utterance per press, like a smart speaker
    let final = '';
    recognition.onresult = (event) => {
      let interim = '';
      for (const result of Array.from(event.results)) {
        if (result.isFinal) {
          final += result[0].transcript;
        } else {
          interim += result[0].transcript;
        }
      }
      this.heard.set((final + interim).trim());
    };
    recognition.onerror = (event) => {
      this.problem.set(
        event.error === 'not-allowed' || event.error === 'service-not-allowed'
          ? 'Microphone access is blocked. Allow it in the address bar, or type instead.'
          : event.error === 'no-speech'
            ? null
            : "I couldn't hear that. Please try again, or type instead.",
      );
    };
    recognition.onend = () => {
      this.listening.set(false);
      this.recognition = null;
      const words = final.trim();
      this.heard.set('');
      if (words) {
        onFinal(words);
      }
    };
    this.problem.set(null);
    this.heard.set('');
    this.recognition = recognition;
    this.listening.set(true);
    try {
      recognition.start();
    } catch {
      this.listening.set(false);
      this.problem.set("The microphone couldn't start. Please type instead.");
    }
  }

  /** Stop listening; anything heard so far is still sent. */
  stop(): void {
    this.recognition?.stop();
  }
}
