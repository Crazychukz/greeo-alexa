import {
  ChangeDetectionStrategy,
  Component,
  DOCUMENT,
  ElementRef,
  computed,
  effect,
  inject,
  input,
  output,
  signal,
  untracked,
} from '@angular/core';

/** What Greeo is doing; Mbe shows it. */
export type MbeState = 'idle' | 'resting' | 'listening' | 'speaking' | 'thinking';
export type MbePose = 'standing' | 'seated';
type Pose = MbePose;

const LABELS: Record<MbeState, string> = {
  idle: 'Mbe the tortoise, resting',
  resting: 'Mbe the tortoise, resting on his stool',
  listening: 'Mbe the tortoise, listening',
  speaking: 'Mbe the tortoise, telling a story',
  thinking: 'Mbe the tortoise, thinking',
};

/** Mbe stands to rest and listen, and sits on his stool to rest, think and tell stories. */
const POSE: Record<MbeState, Pose> = {
  idle: 'standing',
  resting: 'seated',
  listening: 'standing',
  speaking: 'seated',
  thinking: 'seated',
};

/** The clip that carries him into each pose; played once, between loops. */
const INTO: Record<Pose, string> = { seated: 'sit-down', standing: 'stand-up' };
const TRANSITIONS = new Set(Object.values(INTO));
const CLIPS = ['idle', 'listening', 'speaking', 'thinking', 'sit-down', 'stand-up'];
/**
 * Seated resting has no clip yet: Mbe rests as the seated still with a gentle breathing
 * motion. When a resting.webm/.mov exists, add 'resting' to CLIPS and drop this.
 */
const REST = 'rest';
const STILLS: Record<Pose, string> = { standing: '/mbe/mbe.png', seated: '/mbe/mbe-seated.png' };
/** If a transition never reports its end (a failed load), move on anyway. */
const TRANSITION_TIMEOUT_MS = 5000;

/**
 * Mbe, Greeo's storyteller: the tortoise of Igbo folktales, after the fall. The cracks in
 * his shell glow like embers; they remind him that tricks crack you open, so now he only
 * tells true stories.
 *
 * Each state is a transparent looping clip from public/mbe/. When the pose changes, the
 * sit-down or stand-up clip plays first; a state change during it waits for it to end.
 * Browsers disagree on transparent video (Safari: HEVC .mov; Chrome and Firefox: VP9
 * .webm), so the file is chosen per browser. With reduced motion Mbe is a still image.
 */
@Component({
  selector: 'greeo-mbe',
  templateUrl: './mbe.html',
  styleUrl: './mbe.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
  host: {
    role: 'img',
    '[attr.aria-label]': 'label()',
    '[attr.data-state]': 'state()',
  },
})
export class Mbe {
  readonly state = input<MbeState>('idle');
  /**
   * The pose Mbe appears in. If it differs from his first state's pose he moves into it
   * on arrival, for example enterFrom="seated" with state="idle" stands him up.
   */
  readonly enterFrom = input<MbePose | null>(null);
  /**
   * Playback speed of his loops (not the sit-down/stand-up transitions): 1 is natural,
   * below 1 is slower and calmer, for example 0.65 for a slow, continuous story on home.
   */
  readonly speed = input(1);
  /** Mbe has reached his first state (after any arrival transition, such as sitting down). */
  readonly arrived = output<void>();
  private hasArrived = false;

  private readonly host = inject<ElementRef<HTMLElement>>(ElementRef);
  private readonly window = inject(DOCUMENT).defaultView;
  private pose: Pose | null = null;
  private transitionTimer: ReturnType<typeof setTimeout> | undefined;

  protected readonly clips = CLIPS;
  protected readonly rest = REST;
  protected readonly seatedStill = STILLS.seated;
  protected readonly extension = prefersHevcAlpha(this.window) ? 'mov' : 'webm';
  protected readonly reducedMotion =
    this.window?.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false;
  protected readonly label = computed(() => LABELS[this.state()]);
  protected readonly still = computed(() => STILLS[POSE[this.state()]]);
  /** The clip on screen: a state's loop, or a transition on its way to one. */
  protected readonly showing = signal<string>('idle');

  constructor() {
    effect(() => {
      const state = this.state();
      untracked(() => this.show(state));
    });
  }

  protected isLoop(clip: string): boolean {
    return !TRANSITIONS.has(clip);
  }

  /** A transition finished: carry on to whatever state Mbe should be in now. */
  protected transitionEnded(clip: string): void {
    if (clip === this.showing() && TRANSITIONS.has(clip)) {
      clearTimeout(this.transitionTimer);
      this.transitionTimer = undefined;
      this.show(this.state());
    }
  }

  private show(state: MbeState): void {
    if (this.transitionTimer) {
      return; // mid sit-down or stand-up: transitionEnded picks up the latest state
    }
    const target = POSE[state];
    this.pose ??= this.enterFrom(); // first show: start where the page asked him to be
    if (this.pose !== null && this.pose !== target && !this.reducedMotion) {
      this.pose = target;
      this.play(INTO[target]);
      this.transitionTimer = setTimeout(
        () => this.transitionEnded(INTO[target]),
        TRANSITION_TIMEOUT_MS,
      );
      return;
    }
    this.pose = target;
    if (state === 'resting') {
      this.showing.set(REST);
    } else {
      this.play(state);
    }
    if (!this.hasArrived) {
      this.hasArrived = true;
      this.arrived.emit();
    }
  }

  private play(clip: string): void {
    this.showing.set(clip);
    const video = this.host.nativeElement.querySelector<HTMLVideoElement>(
      `video[data-clip="${clip}"]`,
    );
    if (video && TRANSITIONS.has(clip)) {
      video.currentTime = 0; // transitions always start from the beginning
    }
    try {
      // play() returns a Promise in modern browsers and nothing in older ones (and jsdom).
      void video?.play?.()?.catch(() => undefined);
    } catch {
      // Autoplay refused or video unsupported: Mbe stays on his current frame.
    }
  }
}

/** Safari (WebKit) is the browser that needs HEVC for transparent video. */
function prefersHevcAlpha(window: Window | null): boolean {
  const navigator = window?.navigator;
  return !!navigator && /Apple/.test(navigator.vendor) && !/CriOS|FxiOS/.test(navigator.userAgent);
}
