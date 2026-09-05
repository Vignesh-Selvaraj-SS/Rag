import { ChangeDetectionStrategy, Component, computed, effect, inject, input, signal } from '@angular/core';
import { DatePipe, JsonPipe } from '@angular/common';
import { RouterLink } from '@angular/router';
import { firstValueFrom } from 'rxjs';
import { ApiError, ReplayResponse, TraceDetail } from '../../../core/models';
import { ServerConfigService } from '../../../core/services/server-config.service';
import { TraceApiService } from '../../../core/services/trace-api.service';
import { ChunkCard } from '../../../shared/components/chunk-card/chunk-card';
import { ErrorState } from '../../../shared/components/error-state/error-state';
import { LoadingIndicator } from '../../../shared/components/loading-indicator/loading-indicator';
import { StatusBadge } from '../../../shared/components/status-badge/status-badge';
import { DurationPipe } from '../../../shared/pipes/duration.pipe';
import { MarkdownPipe } from '../../../shared/pipes/markdown.pipe';

@Component({
  selector: 'app-trace-detail',
  imports: [DatePipe, JsonPipe, RouterLink, ChunkCard, ErrorState, LoadingIndicator, StatusBadge, DurationPipe, MarkdownPipe],
  templateUrl: './trace-detail.html',
  styleUrl: './trace-detail.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class TraceDetailPage {
  /** Route parameter, bound by withComponentInputBinding. */
  readonly traceId = input.required<string>();

  private readonly api = inject(TraceApiService);
  protected readonly serverConfig = inject(ServerConfigService);

  protected readonly trace = signal<TraceDetail | null>(null);
  protected readonly loading = signal(true);
  protected readonly error = signal<ApiError | null>(null);

  protected readonly replay = signal<ReplayResponse | null>(null);
  protected readonly replaying = signal(false);
  protected readonly replayError = signal<ApiError | null>(null);

  protected readonly citedIds = computed(() => new Set(this.trace()?.cited_chunk_ids ?? []));
  protected readonly minScore = computed(() => Number(this.trace()?.params['min_score'] ?? 0));
  protected readonly notCosine = computed(() => ['hybrid', 'rerank'].includes(String(this.trace()?.params['mode'] ?? '')));

  constructor() {
    this.serverConfig.load();
    effect(() => {
      const id = this.traceId();
      void this.load(id);
    });
  }

  async load(id: string = this.traceId()): Promise<void> {
    this.loading.set(true);
    this.error.set(null);
    this.replay.set(null);
    try {
      this.trace.set(await firstValueFrom(this.api.get(id)));
    } catch (error) {
      this.error.set(error as ApiError);
    } finally {
      this.loading.set(false);
    }
  }

  async runReplay(): Promise<void> {
    if (this.replaying()) {
      return;
    }
    this.replaying.set(true);
    this.replayError.set(null);
    try {
      this.replay.set(await firstValueFrom(this.api.replay(this.traceId())));
    } catch (error) {
      this.replayError.set(error as ApiError);
    } finally {
      this.replaying.set(false);
    }
  }

  protected diffClass(line: string): string {
    if (line.startsWith('+') && !line.startsWith('+++')) {
      return 'diff__add';
    }
    if (line.startsWith('-') && !line.startsWith('---')) {
      return 'diff__del';
    }
    if (line.startsWith('@@')) {
      return 'diff__hunk';
    }
    return '';
  }
}
