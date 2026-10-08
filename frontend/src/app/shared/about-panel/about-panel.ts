import {
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  afterNextRender,
  inject,
  output,
  signal,
  viewChild,
} from '@angular/core';

/** One fact about Greeo, shown as a tile: an icon, a name and a line of detail. */
interface AboutTile {
  icon: keyof typeof ICONS;
  title: string;
  text: string;
}

interface AboutSection {
  key: 'inspiration' | 'tech' | 'execution';
  label: string;
  icon: keyof typeof ICONS;
  tiles: AboutTile[];
}

/** Line icons on a 24-unit grid, drawn with stroke only. */
export const ICONS = {
  spark: 'M12 3v4M12 17v4M3 12h4M17 12h4M6 6l2.5 2.5M15.5 15.5L18 18M6 18l2.5-2.5M15.5 8.5L18 6',
  fire: 'M12 21c-4 0-6.5-2.7-6.5-6 0-3.5 3-5.5 3.5-9 2 1.5 3 3.5 3 5 1-1 1.5-2.5 1.5-4 2.5 2 5 5 5 8 0 3.3-2.5 6-6.5 6z',
  tortoise:
    'M4 15c0-4 3.5-7 8-7s8 3 8 7H4zM20 13l2-1M6 15v3M10 15v3M14 15v3M18 15v3M9 8l1.5 3.5L14 8',
  scale: 'M12 4v16M5 20h14M4 9h16M6 9l-3 6h6zM18 9l-3 6h6z',
  family: 'M8 11a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM16 11a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM2 20c0-3.3 2.7-6 6-6s6 2.7 6 6M12 20c0-3.3 1.8-6 4-6s6 2.7 6 6',
  quote: 'M7 8h4v4c0 2.5-1.5 4-4 4M15 8h4v4c0 2.5-1.5 4-4 4',
  plug: 'M9 3v5M15 3v5M6 8h12v3a6 6 0 0 1-12 0zM12 17v4',
  cloud: 'M7 18a4 4 0 0 1-.5-8A6 6 0 0 1 18 9a4.5 4.5 0 0 1-.5 9z',
  wave: 'M3 12h2M7 8v8M11 5v14M15 8v8M19 11v2M21 12h0',
  stack: 'M12 3l9 5-9 5-9-5zM3 13l9 5 9-5M3 17.5l9 5 9-5',
  screen: 'M3 4h18v12H3zM9 20h6M12 16v4',
  news: 'M4 5h13v14H6a2 2 0 0 1-2-2zM17 9h3v8a2 2 0 0 1-2 2M7 9h7M7 13h7M7 16h4',
  flow: 'M4 6h5v4H4zM15 6h5v4h-5zM9.5 18h5v-4h-5zM9 8h6M12 10v4',
  layers: 'M12 3l9 4.5-9 4.5-9-4.5zM3 12l9 4.5 9-4.5M3 16.5l9 4.5 9-4.5',
  shield: 'M12 3l8 3v6c0 4.5-3.5 8-8 9-4.5-1-8-4.5-8-9V6zM8.5 12l2.5 2.5 4.5-5',
  gauge: 'M4 18a8 8 0 1 1 16 0M12 18l4-6M8 9.5l.5.8M12 8v1M16 9.5l-.5.8',
  check: 'M4 12.5l5 5L20 6.5',
  clock: 'M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 7v5l3 2',
  info: 'M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 11v6M12 7.5v.5',
  bolt: 'M13 3L5 13h6l-1 8 8-10h-6z',
  cog: 'M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9L7 7M17 17l2.1 2.1M4.9 19.1L7 17M17 7l2.1-2.1',
} as const;

/** What Greeo is and how it was made, in three pages, shown over the device's screen. */
export const SECTIONS: AboutSection[] = [
  {
    key: 'inspiration',
    label: 'Inspiration',
    icon: 'spark',
    tiles: [
      {
        icon: 'fire',
        title: 'The griot',
        text: "West Africa's keepers of memory tell history as story, with proverbs, so it is remembered.",
      },
      {
        icon: 'clock',
        title: 'News, made memorable',
        text: "Today's news moves fast. Told as a tale, it is easier to follow, recall and share.",
      },
      {
        icon: 'tortoise',
        title: 'Mbe the tortoise',
        text: 'The clever, patient tortoise of Igbo and Yoruba folktales is your storyteller.',
      },
      {
        icon: 'scale',
        title: 'Truth first',
        text: 'A tale may paint and exaggerate, but it borrows from the facts and never bends them.',
      },
      {
        icon: 'quote',
        title: 'Real proverbs',
        text: 'Every proverb comes from a checked collection. Greeo never makes one up.',
      },
      {
        icon: 'family',
        title: 'Story time together',
        text: 'Made for the kitchen and the living room: a story the whole family can hear.',
      },
    ],
  },
  {
    key: 'tech',
    label: 'The tech',
    icon: 'cog',
    tiles: [
      {
        icon: 'plug',
        title: 'Alexa+ add-on',
        text: 'An MCP server gives Alexa+ tools for tales, facts and sources, with visual cards.',
      },
      {
        icon: 'cloud',
        title: 'Amazon Bedrock',
        text: 'Kimi K2.5 writes the tales. Qwen3 finds the facts, picks proverbs and edits.',
      },
      {
        icon: 'wave',
        title: 'Amazon Polly',
        text: 'Storyteller voices, paced with pauses so each tale is told, not read.',
      },
      {
        icon: 'stack',
        title: 'The backend',
        text: 'Django, Postgres, Redis and Celery: new stories are made twice an hour.',
      },
      {
        icon: 'screen',
        title: 'This screen',
        text: 'Angular simulates an Echo Show, with Mbe and soft drums under each tale.',
      },
      {
        icon: 'news',
        title: 'Open news',
        text: 'BBC, Al Jazeera, The Guardian and DW. Robots.txt is respected; no article is stored.',
      },
    ],
  },
  {
    key: 'execution',
    label: 'Execution',
    icon: 'bolt',
    tiles: [
      {
        icon: 'flow',
        title: 'The pipeline',
        text: 'Read the article, set down the facts, choose proverbs, tell, check, revise, publish.',
      },
      {
        icon: 'layers',
        title: 'Seven layers',
        text: 'Tale, reflection, proverbs, facts, context, perspectives and sources, on request.',
      },
      {
        icon: 'shield',
        title: 'Two checks',
        text: 'Rules catch new names and numbers; an editor model catches invented detail.',
      },
      {
        icon: 'info',
        title: 'Handled with care',
        text: 'Stories of death or conflict get no jokes and no proverbs, only a quiet telling.',
      },
      {
        icon: 'gauge',
        title: 'Budgeted and logged',
        text: 'Every model call is counted against a daily budget and recorded for review.',
      },
      {
        icon: 'check',
        title: 'Tested',
        text: 'Over 300 automated tests cover the pipeline, the tools, the host and this screen.',
      },
    ],
  },
];

/**
 * About Greeo: the inspiration, the tech and how it was built. Styled after the device's
 * own quick-settings panel; it sits over the screen and closes with ×, Escape or a tap
 * outside the panel.
 */
@Component({
  selector: 'greeo-about-panel',
  templateUrl: './about-panel.html',
  styleUrl: './about-panel.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
  host: { '(keydown.escape)': 'closed.emit()' },
})
export class AboutPanel {
  readonly closed = output<void>();

  protected readonly sections = SECTIONS;
  protected readonly icons = ICONS;
  protected readonly current = signal(0);

  private readonly closeButton = viewChild.required<ElementRef<HTMLButtonElement>>('close');

  constructor() {
    // Put focus inside the panel, so keyboard and screen-reader users land in it.
    afterNextRender(() => this.closeButton().nativeElement.focus());
  }

  protected show(index: number): void {
    this.current.set(index);
  }
}
