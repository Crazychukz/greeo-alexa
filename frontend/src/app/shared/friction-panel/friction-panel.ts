import {
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  afterNextRender,
  computed,
  output,
  signal,
  viewChild,
} from '@angular/core';

import {
  FRICTION_LOG_MARKDOWN,
  FrictionEntry,
  FrictionGroup,
  parseFrictionLog,
} from './friction-log';

type Filter = 'All' | FrictionGroup;

/** Pill icons on a 24-unit grid, stroke only. */
const ICONS: Record<Filter, string> = {
  All: 'M4 6h16M4 12h16M4 18h10',
  'Alexa+': 'M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM8 13a4 4 0 0 0 8 0',
  AWS: 'M7 18a4 4 0 0 1-.5-8A6 6 0 0 1 18 9a4.5 4.5 0 0 1-.5 9z',
  'MCP SDK': 'M9 3v5M15 3v5M6 8h12v3a6 6 0 0 1-12 0zM12 17v4',
  Other: 'M5 12h.01M12 12h.01M19 12h.01',
};

/**
 * The friction log: every problem with a tool or doc that slowed Greeo down, read from
 * docs/FRICTION_LOG.md. Tiles list the entries; opening one shows it in full.
 */
@Component({
  selector: 'greeo-friction-panel',
  templateUrl: './friction-panel.html',
  // The sheet, pills, tiles and buttons are the About panel's; only the entry view is new.
  styleUrls: ['../about-panel/about-panel.scss', './friction-panel.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
  host: { '(keydown.escape)': 'onEscape()' },
})
export class FrictionPanel {
  readonly closed = output<void>();

  protected readonly entries = parseFrictionLog(FRICTION_LOG_MARKDOWN);
  protected readonly icons = ICONS;
  /** Only the groups that have entries, after "All". */
  protected readonly filters: Filter[] = [
    'All',
    ...(['Alexa+', 'AWS', 'MCP SDK', 'Other'] as const).filter((group) =>
      this.entries.some((entry) => entry.group === group),
    ),
  ];
  protected readonly filter = signal<Filter>('All');
  protected readonly shown = computed(() =>
    this.filter() === 'All'
      ? this.entries
      : this.entries.filter((entry) => entry.group === this.filter()),
  );
  /** The entry being read in full, or none while the list shows. */
  protected readonly open = signal<FrictionEntry | null>(null);

  private readonly closeButton = viewChild.required<ElementRef<HTMLButtonElement>>('close');

  constructor() {
    afterNextRender(() => this.closeButton().nativeElement.focus());
  }

  protected countIn(filter: Filter): number {
    return filter === 'All'
      ? this.entries.length
      : this.entries.filter((entry) => entry.group === filter).length;
  }

  protected choose(filter: Filter): void {
    this.filter.set(filter);
    this.open.set(null);
  }

  /** Escape steps back from an open entry first, then closes the panel. */
  protected onEscape(): void {
    if (this.open()) {
      this.open.set(null);
    } else {
      this.closed.emit();
    }
  }
}
