import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';
import { JsonPipe } from '@angular/common';
import { ChatResponse } from '../../../../core/models';
import { ChunkCard } from '../../../../shared/components/chunk-card/chunk-card';

/**
 * Developer-mode panel under an answer: what was retrieved, the gate
 * decision, the resolved parameters and the raw model output.
 */
@Component({
  selector: 'app-retrieval-details',
  imports: [JsonPipe, ChunkCard],
  template: `
    @if (response().debug; as debug) {
      <section class="details">
        <div class="details__summary">
          <span class="badge" [class.badge--success]="debug.passes_gate" [class.badge--warning]="!debug.passes_gate">
            gate {{ debug.passes_gate ? 'passed' : 'blocked' }}
          </span>
          <span class="small muted">best similarity <span class="mono">{{ debug.best_score }}</span> · gate <span class="mono">{{ minScore() }}</span></span>
          <span class="small muted">model <span class="mono">{{ debug.model }}</span></span>
          <span class="small muted">prompt <span class="mono">{{ debug.prompt_version }}</span></span>
          @if (debug.invalid_citations.length) {
            <span class="badge badge--danger">invented citations: {{ debug.invalid_citations.join(', ') }}</span>
          }
        </div>

        <h4 class="details__heading">Retrieved chunks ({{ debug.retrieved.length }})</h4>
        <div class="details__chunks">
          @for (chunk of debug.retrieved; track chunk.chunk_id) {
            <app-chunk-card
              [chunk]="chunk"
              [gate]="minScore()"
              [cited]="citedIds().has(chunk.chunk_id)"
              [highlighted]="highlightedRank() === chunk.rank"
              [showDenseSeparately]="notCosine()"
            />
          }
        </div>

        <details class="disclosure">
          <summary>Parameters</summary>
          <pre class="small">{{ debug.params | json }}</pre>
        </details>

        @if (debug.raw_output !== null && debug.raw_output !== response().answer) {
          <details class="disclosure">
            <summary>Raw model output</summary>
            <pre class="small">{{ debug.raw_output }}</pre>
          </details>
        }
      </section>
    }
  `,
  styles: `
    .details {
      display: flex;
      flex-direction: column;
      gap: 10px;
      padding: 12px 14px;
      border: 1px dashed var(--border-strong);
      border-radius: var(--radius);
      background: var(--bg-muted);
    }
    .details__summary {
      display: flex;
      align-items: center;
      gap: 12px;
      flex-wrap: wrap;
    }
    .details__heading {
      font-size: 0.8rem;
      text-transform: uppercase;
      letter-spacing: 0.04em;
      color: var(--text-muted);
    }
    .details__chunks {
      display: flex;
      flex-direction: column;
      gap: 8px;
    }
    pre {
      margin: 6px 0 0;
      white-space: pre-wrap;
    }
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class RetrievalDetails {
  readonly response = input.required<ChatResponse>();
  readonly highlightedRank = input<number | null>(null);

  protected readonly citedIds = computed(() => new Set(this.response().sources.map((source) => source.chunk_id)));
  protected readonly minScore = computed(() => Number(this.response().debug?.params['min_score'] ?? 0));
  protected readonly notCosine = computed(() => ['hybrid', 'rerank'].includes(this.response().mode));
}
