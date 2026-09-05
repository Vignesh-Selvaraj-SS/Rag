import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';
import { DecimalPipe } from '@angular/common';

/**
 * A similarity score as a small bar. `threshold` draws the gate line so a
 * reader sees at a glance whether a chunk cleared it.
 */
@Component({
  selector: 'app-score-bar',
  template: `
    <div class="score" [title]="title()">
      <div class="score__track">
        <div class="score__fill" [class.score__fill--weak]="weak()" [style.width.%]="percent()"></div>
        @if (threshold() !== null) {
          <div class="score__gate" [style.left.%]="(threshold() ?? 0) * 100"></div>
        }
      </div>
      <span class="score__value mono">{{ value() | number: '1.2-3' }}</span>
    </div>
  `,
  styles: `
    .score {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      min-width: 130px;
    }
    .score__track {
      position: relative;
      flex: 1;
      height: 6px;
      border-radius: 3px;
      background: var(--bg-muted);
      overflow: visible;
    }
    .score__fill {
      height: 100%;
      border-radius: 3px;
      background: var(--accent);
    }
    .score__fill--weak {
      background: var(--warning);
    }
    .score__gate {
      position: absolute;
      top: -3px;
      width: 2px;
      height: 12px;
      background: var(--text-faint);
    }
    .score__value {
      min-width: 3.2em;
      text-align: right;
      color: var(--text-muted);
    }
  `,
  imports: [DecimalPipe],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ScoreBar {
  readonly value = input.required<number>();
  /** Gate threshold on the same scale, or null when the score is not a similarity. */
  readonly threshold = input<number | null>(null);
  /** Upper bound of the scale (1 for cosine, small values for RRF/cross-encoder). */
  readonly max = input(1);

  protected readonly percent = computed(() => Math.max(0, Math.min(100, (this.value() / (this.max() || 1)) * 100)));
  protected readonly weak = computed(() => this.threshold() !== null && this.value() < (this.threshold() ?? 0));
  protected readonly title = computed(() =>
    this.threshold() === null ? `score ${this.value()}` : `score ${this.value()} (gate ${this.threshold()})`,
  );
}
