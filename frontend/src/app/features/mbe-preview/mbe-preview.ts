import { ChangeDetectionStrategy, Component, signal } from '@angular/core';

import { Mbe, MbeState } from '../../shared/mbe/mbe';

/** Development page: switch Mbe between states to see the loops and transitions. */
@Component({
  selector: 'greeo-mbe-preview',
  imports: [Mbe],
  template: `
    <section class="preview">
      <greeo-mbe [state]="state()" />
      <div class="states" role="group" aria-label="Mbe's state">
        @for (option of states; track option) {
          <button
            type="button"
            [class.on]="option === state()"
            [attr.aria-pressed]="option === state()"
            (click)="state.set(option)"
          >
            {{ option }}
          </button>
        }
      </div>
    </section>
  `,
  styles: `
    :host {
      display: block;
      height: 100%;
    }
    .preview {
      height: 100%;
      display: grid;
      grid-template-rows: 1fr auto;
      justify-items: center;
      align-items: end;
      gap: 12px;
      padding: 8% 4% 5%;
    }
    greeo-mbe {
      height: 100%;
      width: auto;
      max-height: 100%;
    }
    .states {
      display: flex;
      gap: 8px;
    }
    button {
      padding: 8px 14px;
      border: 1px solid var(--line);
      border-radius: 999px;
      background: transparent;
      color: var(--muted);
      font: 600 13px var(--sans);
      letter-spacing: 0.06em;
      text-transform: uppercase;
      cursor: pointer;
    }
    button.on {
      border-color: transparent;
      background: var(--fire);
      color: var(--on-fire);
    }
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class MbePreview {
  protected readonly states: MbeState[] = ['idle', 'listening', 'thinking', 'speaking'];
  protected readonly state = signal<MbeState>('idle');
}
