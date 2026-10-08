import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  inject,
  signal,
} from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { Router } from '@angular/router';
import { catchError, map, of } from 'rxjs';

import { DemoStory, GreeoApi, StoryShelf } from '../../core/api';
import { openListen } from '../../core/conversation/opening';
import { AskBar } from '../../shared/ask-bar/ask-bar';
import { Mbe } from '../../shared/mbe/mbe';

/** The device's home screen: a greeting, the truth layers, and what to try asking. */
@Component({
  selector: 'greeo-landing',
  imports: [AskBar, Mbe],
  templateUrl: './landing.html',
  styleUrl: './landing.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class Landing {
  protected readonly greeting = signal(greetingFor(new Date()));

  private readonly router = inject(Router);

  protected readonly shelf = toSignal<StoryShelf | null | undefined>(
    inject(GreeoApi)
      .stories()
      .pipe(
        map((shelf) => shelf as StoryShelf | null),
        catchError(() => of(null)),
      ),
    { initialValue: undefined },
  );

  protected readonly featured = computed(() => this.shelf()?.demo[0] ?? null);
  protected readonly stories = computed(() => this.shelf()?.demo.slice(1, 6) ?? []);

  protected tell(story: DemoStory): void {
    void openListen(this.router, { text: `Tell me ${story.title}`, storyId: story.story_id });
  }

  /** Today's-news tile: ask for the briefing, as a listener would. */
  protected hearToday(): void {
    void openListen(this.router, { text: "What's happening today?" });
  }

  constructor() {
    // Re-check each minute, so a page left open greets correctly as the day turns.
    const timer = setInterval(() => this.greeting.set(greetingFor(new Date())), 60_000);
    inject(DestroyRef).onDestroy(() => clearInterval(timer));
  }

  protected readonly layers = [
    'Tale',
    'Reflection',
    'Proverbs',
    'Facts',
    'Context',
    'Perspectives',
    'Sources',
  ];

  protected readonly tryAsking = [
    "What's happening today?",
    'Tell me the story',
    'What does that proverb mean?',
    'Who reported this?',
  ];
}

/** Morning until noon, afternoon until 5pm, evening after that and through the night. */
export function greetingFor(date: Date): string {
  const hour = date.getHours();
  if (hour >= 5 && hour < 12) {
    return 'Good morning';
  }
  if (hour >= 12 && hour < 17) {
    return 'Good afternoon';
  }
  return 'Good evening';
}
