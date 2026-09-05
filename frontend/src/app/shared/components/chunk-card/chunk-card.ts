import { ChangeDetectionStrategy, Component, input } from '@angular/core';
import { DecimalPipe } from '@angular/common';
import { ScoreBar } from '../score-bar/score-bar';

export interface ChunkView {
  rank: number;
  chunk_id: string;
  source: string;
  heading: string;
  page: string;
  score: number;
  dense_score: number;
  text: string | null;
}

/**
 * One retrieved chunk: where it came from, how it scored, and its text.
 * `denseOnly` controls whether the ranking score differs from cosine
 * similarity (hybrid / rerank), in which case both are shown.
 */
@Component({
  selector: 'app-chunk-card',
  imports: [DecimalPipe, ScoreBar],
  template: `
    <article class="chunk" [class.chunk--highlight]="highlighted()" [class.chunk--expected]="expected()">
      <header class="chunk__header">
        <span class="chunk__rank mono">S{{ chunk().rank }}</span>
        <div class="chunk__where">
          <span class="chunk__source">{{ chunk().source }}</span>
          <span class="chunk__heading muted">› {{ chunk().heading }} <span class="faint">({{ chunk().page }})</span></span>
        </div>
        @if (expected()) {
          <span class="badge badge--success">Expected</span>
        }
        @if (cited()) {
          <span class="badge badge--accent">Cited</span>
        }
      </header>
      <div class="chunk__scores">
        @if (showDenseSeparately()) {
          <span class="small muted">rank score <span class="mono">{{ chunk().score | number: '1.3-4' }}</span></span>
          <span class="small muted">similarity</span>
        }
        <app-score-bar [value]="chunk().dense_score" [threshold]="gate()" />
      </div>
      @if (chunk().text) {
        <details class="disclosure">
          <summary>Text</summary>
          <pre class="chunk__text">{{ chunk().text }}</pre>
        </details>
      }
    </article>
  `,
  styles: `
    .chunk {
      border: 1px solid var(--border);
      border-radius: var(--radius);
      padding: 10px 12px;
      background: var(--bg-elevated);
      display: flex;
      flex-direction: column;
      gap: 6px;
    }
    .chunk--highlight {
      border-color: var(--accent);
      box-shadow: 0 0 0 2px color-mix(in srgb, var(--accent) 25%, transparent);
    }
    .chunk--expected {
      border-color: var(--success);
    }
    .chunk__header {
      display: flex;
      align-items: center;
      gap: 8px;
      flex-wrap: wrap;
    }
    .chunk__rank {
      font-weight: 700;
      color: var(--accent);
    }
    .chunk__where {
      display: flex;
      flex-direction: column;
      min-width: 0;
      flex: 1;
      font-size: 0.85rem;
    }
    .chunk__source {
      font-weight: 600;
    }
    .chunk__scores {
      display: flex;
      align-items: center;
      gap: 12px;
      flex-wrap: wrap;
    }
    .chunk__text {
      white-space: pre-wrap;
      font-size: 0.82rem;
      max-height: 260px;
      margin: 6px 0 0;
    }
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ChunkCard {
  readonly chunk = input.required<ChunkView>();
  readonly gate = input<number | null>(null);
  readonly highlighted = input(false);
  readonly cited = input(false);
  readonly expected = input(false);
  /** True for hybrid / rerank where `score` is not a cosine similarity. */
  readonly showDenseSeparately = input(false);
}
