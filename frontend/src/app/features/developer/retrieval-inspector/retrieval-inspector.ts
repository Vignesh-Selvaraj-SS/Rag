import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { firstValueFrom } from 'rxjs';
import { ApiError, RetrievalMode, SearchResponse } from '../../../core/models';
import { ChatApiService } from '../../../core/services/chat-api.service';
import { PreferencesStore } from '../../../core/services/preferences-store.service';
import { ServerConfigService } from '../../../core/services/server-config.service';
import { ChunkCard } from '../../../shared/components/chunk-card/chunk-card';
import { EmptyState } from '../../../shared/components/empty-state/empty-state';
import { ErrorState } from '../../../shared/components/error-state/error-state';
import { LoadingIndicator } from '../../../shared/components/loading-indicator/loading-indicator';
import { DurationPipe } from '../../../shared/pipes/duration.pipe';

/**
 * Retrieval only, no answer: which chunks a question surfaces under each
 * mode, their scores, and whether the similarity gate would pass.
 * Successor to `ask.py --search-only` and the Week 4 inspection view.
 */
@Component({
  selector: 'app-retrieval-inspector',
  imports: [ReactiveFormsModule, ChunkCard, EmptyState, ErrorState, LoadingIndicator, DurationPipe],
  templateUrl: './retrieval-inspector.html',
  styleUrl: './retrieval-inspector.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class RetrievalInspector {
  private readonly api = inject(ChatApiService);
  private readonly formBuilder = inject(FormBuilder).nonNullable;
  private readonly preferences = inject(PreferencesStore);
  protected readonly serverConfig = inject(ServerConfigService);

  protected readonly form = this.formBuilder.group({
    question: this.formBuilder.control('', [Validators.required, Validators.maxLength(2000)]),
    mode: this.formBuilder.control<RetrievalMode>(this.preferences.mode()),
    topK: this.formBuilder.control(10, [Validators.min(1), Validators.max(50)]),
    minScore: this.formBuilder.control<number | null>(null, [Validators.min(0), Validators.max(1)]),
    source: this.formBuilder.control(''),
  });

  protected readonly result = signal<SearchResponse | null>(null);
  protected readonly loading = signal(false);
  protected readonly error = signal<ApiError | null>(null);
  protected readonly compare = signal<Record<string, SearchResponse | ApiError> | null>(null);
  protected readonly comparing = signal(false);

  protected readonly notCosine = computed(() => ['hybrid', 'rerank'].includes(this.result()?.mode ?? ''));
  protected readonly compareModes = computed(() =>
    this.serverConfig.modes().filter((mode) => !mode.requires_llm || this.serverConfig.llmConfigured()),
  );

  constructor() {
    this.serverConfig.load();
  }

  async search(): Promise<void> {
    if (this.form.invalid || this.loading()) {
      this.form.markAllAsTouched();
      return;
    }
    this.loading.set(true);
    this.error.set(null);
    this.compare.set(null);
    try {
      this.result.set(await firstValueFrom(this.api.search(this.request(this.form.controls.mode.value))));
    } catch (error) {
      this.error.set(error as ApiError);
      this.result.set(null);
    } finally {
      this.loading.set(false);
    }
  }

  /** Run the same question through every available mode and show the rankings side by side. */
  async compareAll(): Promise<void> {
    if (this.form.controls.question.invalid || this.comparing()) {
      return;
    }
    this.comparing.set(true);
    const results: Record<string, SearchResponse | ApiError> = {};
    for (const mode of this.compareModes()) {
      try {
        results[mode.id] = await firstValueFrom(this.api.search({ ...this.request(mode.id), top_k: 5 }));
      } catch (error) {
        results[mode.id] = error as ApiError;
      }
    }
    this.compare.set(results);
    this.comparing.set(false);
  }

  protected isError(value: SearchResponse | ApiError): value is ApiError {
    return 'message' in value && 'status' in value;
  }

  protected asResponse(value: SearchResponse | ApiError): SearchResponse | null {
    return this.isError(value) ? null : value;
  }

  protected asError(value: SearchResponse | ApiError): ApiError | null {
    return this.isError(value) ? value : null;
  }

  protected compareEntries(): { mode: string; value: SearchResponse | ApiError }[] {
    const compare = this.compare();
    return compare ? Object.entries(compare).map(([mode, value]) => ({ mode, value })) : [];
  }

  private request(mode: RetrievalMode) {
    const value = this.form.getRawValue();
    return {
      question: value.question.trim(),
      mode,
      top_k: Number(value.topK) || null,
      min_score: value.minScore === null || (value.minScore as unknown) === '' ? null : Number(value.minScore),
      source: value.source.trim() || null,
    };
  }
}
