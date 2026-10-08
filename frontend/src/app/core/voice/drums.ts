import { DestroyRef, Injectable, effect, inject } from '@angular/core';

import { Conversation } from '../conversation/conversation';
import { Speech } from './speech';

/** How loud the drums sit under Greeo's voice: felt more than heard. */
export const DRUM_VOLUME = 0.07;
const FADE_SECONDS = 1.8;
/** Eighth notes per minute: a slow, walking 12/8. */
const PULSE = 210;
const LOOKAHEAD_SECONDS = 0.25;

type Stroke = 'bass' | 'tone' | 'slap' | 'shaker';

/**
 * One bar of 12/8, a gentle djembe-style figure: bass on the downbeats, open tones
 * answering, a soft slap, and a shaker breathing underneath.
 */
export const PATTERN: readonly (readonly Stroke[])[] = [
  ['bass', 'shaker'],
  ['shaker'],
  [],
  ['tone', 'shaker'],
  ['tone'],
  ['shaker'],
  ['slap', 'shaker'],
  ['bass'],
  ['shaker'],
  ['tone', 'shaker'],
  ['slap'],
  ['shaker'],
];

/**
 * Soft drums under a tale, made in the browser (no audio files, nothing to license).
 * They play while a tale tells itself and voice is on, and fade away when it stops.
 * Provided by the listening screen, so they end with it.
 */
@Injectable()
export class Drums {
  private context: AudioContext | null = null;
  private master: GainNode | null = null;
  private noise: AudioBuffer | null = null;
  private timer: ReturnType<typeof setInterval> | null = null;
  private step = 0;
  private nextTime = 0;

  constructor() {
    const conversation = inject(Conversation);
    const speech = inject(Speech);
    effect(() => {
      if (conversation.isTelling() && speech.enabled()) {
        this.start();
      } else {
        this.stop();
      }
    });
    inject(DestroyRef).onDestroy(() => {
      this.stop();
      void this.context?.close();
    });
  }

  get playing(): boolean {
    return this.timer !== null;
  }

  start(): void {
    if (this.timer || !this.ensureContext()) {
      return;
    }
    const context = this.context!;
    void context.resume();
    const now = context.currentTime;
    this.master!.gain.cancelScheduledValues(now);
    this.master!.gain.setValueAtTime(this.master!.gain.value, now);
    this.master!.gain.linearRampToValueAtTime(DRUM_VOLUME, now + FADE_SECONDS);
    this.step = 0;
    this.nextTime = now + 0.05;
    this.timer = setInterval(() => this.schedule(), 100);
    this.schedule();
  }

  stop(): void {
    if (!this.timer || !this.context || !this.master) {
      return;
    }
    clearInterval(this.timer);
    this.timer = null;
    const now = this.context.currentTime;
    this.master.gain.cancelScheduledValues(now);
    this.master.gain.setValueAtTime(this.master.gain.value, now);
    this.master.gain.linearRampToValueAtTime(0, now + FADE_SECONDS);
  }

  private ensureContext(): boolean {
    if (this.context) {
      return true;
    }
    const AudioContextType = globalThis.AudioContext;
    if (!AudioContextType) {
      return false; // no Web Audio (tests, very old browsers): the tale is told without drums
    }
    const context = new AudioContextType();
    // Muffled, as if from across the compound: keeps the drums from fighting the words.
    const muffle = context.createBiquadFilter();
    muffle.type = 'lowpass';
    muffle.frequency.value = 1600;
    const master = context.createGain();
    master.gain.value = 0;
    master.connect(muffle).connect(context.destination);
    const noise = context.createBuffer(1, context.sampleRate, context.sampleRate);
    const samples = noise.getChannelData(0);
    for (let i = 0; i < samples.length; i++) {
      samples[i] = Math.random() * 2 - 1;
    }
    this.context = context;
    this.master = master;
    this.noise = noise;
    return true;
  }

  /** Schedule the strokes that fall within the next moment, a little ahead of time. */
  private schedule(): void {
    const context = this.context!;
    const stepSeconds = 60 / PULSE;
    while (this.nextTime < context.currentTime + LOOKAHEAD_SECONDS) {
      for (const stroke of PATTERN[this.step]) {
        // A human hand: never quite on the grid, never quite the same strength.
        const when = this.nextTime + (Math.random() - 0.5) * 0.016;
        this.play(stroke, Math.max(when, context.currentTime), 0.85 + Math.random() * 0.3);
      }
      this.step = (this.step + 1) % PATTERN.length;
      this.nextTime += stepSeconds;
    }
  }

  private play(stroke: Stroke, when: number, strength: number): void {
    switch (stroke) {
      case 'bass':
        return this.drum(when, 95, 52, 0.5, 1.0 * strength);
      case 'tone':
        return this.drum(when, 230, 185, 0.22, 0.45 * strength);
      case 'slap':
        return this.hiss(when, 'bandpass', 2200, 0.07, 0.4 * strength);
      case 'shaker':
        return this.hiss(when, 'highpass', 6000, 0.04, 0.1 * strength);
    }
  }

  /** A skin struck: a pitch that drops as it rings out. */
  private drum(when: number, from: number, to: number, ring: number, level: number): void {
    const context = this.context!;
    const osc = context.createOscillator();
    osc.type = 'sine';
    osc.frequency.setValueAtTime(from, when);
    osc.frequency.exponentialRampToValueAtTime(to, when + ring * 0.4);
    const gain = context.createGain();
    gain.gain.setValueAtTime(0.0001, when);
    gain.gain.exponentialRampToValueAtTime(level, when + 0.005);
    gain.gain.exponentialRampToValueAtTime(0.0001, when + ring);
    osc.connect(gain).connect(this.master!);
    osc.start(when);
    osc.stop(when + ring + 0.05);
  }

  /** A burst of noise: the slap of a palm, or seeds in a gourd. */
  private hiss(when: number, type: BiquadFilterType, frequency: number, ring: number, level: number): void {
    const context = this.context!;
    const source = context.createBufferSource();
    source.buffer = this.noise;
    const filter = context.createBiquadFilter();
    filter.type = type;
    filter.frequency.value = frequency;
    const gain = context.createGain();
    gain.gain.setValueAtTime(level, when);
    gain.gain.exponentialRampToValueAtTime(0.0001, when + ring);
    source.connect(filter).connect(gain).connect(this.master!);
    source.start(when, Math.random() * 0.5);
    source.stop(when + ring + 0.02);
  }
}
