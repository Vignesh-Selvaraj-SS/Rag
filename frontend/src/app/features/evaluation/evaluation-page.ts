import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { DatePipe, DecimalPipe, PercentPipe } from '@angular/common';
import { FormArray, FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { firstValueFrom } from 'rxjs';
import {
  ApiError,
  EvaluationRun,
  EvaluationRunSummary,
  GoldenQuestion,
  InspectResponse,
  RetrievalMode,
} from '../../core/models';
import { EvaluationApiService } from '../../core/services/evaluation-api.service';
import { NotificationService } from '../../core/services/notification.service';
import { PreferencesStore } from '../../core/services/preferences-store.service';
import { ServerConfigService } from '../../core/services/server-config.service';
import { ChunkCard } from '../../shared/components/chunk-card/chunk-card';
import { ConfirmDialog } from '../../shared/components/confirm-dialog/confirm-dialog';
import { EmptyState } from '../../shared/components/empty-state/empty-state';
import { ErrorState } from '../../shared/components/error-state/error-state';
import { LoadingIndicator } from '../../shared/components/loading-indicator/loading-indicator';
import { PageHeader } from '../../shared/components/page-header/page-header';
import { StatusBadge } from '../../shared/components/status-badge/status-badge';
import { DurationPipe } from '../../shared/pipes/duration.pipe';
import { RelativeTimePipe } from '../../shared/pipes/relative-time.pipe';
import { MarkdownPipe } from '../../shared/pipes/markdown.pipe';

type Tab = 'results' | 'questions' | 'history';

@Component({
  selector: 'app-evaluation-page',
  imports: [
    DatePipe,
    DecimalPipe,
    PercentPipe,
    ReactiveFormsModule,
    ChunkCard,
    ConfirmDialog,
    EmptyState,
    ErrorState,
    LoadingIndicator,
    PageHeader,
    StatusBadge,
    DurationPipe,
    RelativeTimePipe,
    MarkdownPipe,
  ],
  templateUrl: './evaluation-page.html',
  styleUrl: './evaluation-page.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class EvaluationPage {
  private readonly api = inject(EvaluationApiService);
  private readonly notifications = inject(NotificationService);
  private readonly formBuilder = inject(FormBuilder).nonNullable;
  protected readonly serverConfig = inject(ServerConfigService);
  protected readonly developerMode = inject(PreferencesStore).developerMode;

  protected readonly tab = signal<Tab>('results');

  // --- golden set -----------------------------------------------------------
  protected readonly goldenLoading = signal(true);
  protected readonly goldenError = signal<ApiError | null>(null);
  protected readonly goldenSaving = signal(false);
  protected readonly goldenDirty = signal(false);
  protected readonly questions = this.formBuilder.array<ReturnType<EvaluationPage['questionGroup']>>([]);

  // --- runs -----------------------------------------------------------------
  protected readonly runs = signal<EvaluationRunSummary[]>([]);
  protected readonly runsLoading = signal(true);
  protected readonly runsError = signal<ApiError | null>(null);
  protected readonly selectedRun = signal<EvaluationRun | null>(null);
  protected readonly selectedRunLoading = signal(false);
  protected readonly running = signal(false);
  protected readonly runError = signal<ApiError | null>(null);
  protected readonly pendingDeleteRun = signal<EvaluationRunSummary | null>(null);
  protected readonly expandedQuestion = signal<string | null>(null);

  protected readonly runForm = this.formBuilder.group({
    mode: this.formBuilder.control<RetrievalMode>('dense'),
    label: this.formBuilder.control('', [Validators.maxLength(80)]),
  });

  /** The run recorded immediately before the selected one, for a before/after delta. */
  protected readonly previousRun = computed<EvaluationRunSummary | null>(() => {
    const selected = this.selectedRun();
    if (!selected) {
      return null;
    }
    const list = this.runs();
    const index = list.findIndex((run) => run.run_id === selected.run_id);
    return index >= 0 && index + 1 < list.length ? list[index + 1] : null;
  });

  protected readonly failures = computed(() => (this.selectedRun()?.per_question ?? []).filter((q) => !q.hit_at_3));

  // --- inspect --------------------------------------------------------------
  protected readonly inspecting = signal<string | null>(null);
  protected readonly inspection = signal<InspectResponse | null>(null);
  protected readonly inspectError = signal<ApiError | null>(null);

  constructor() {
    this.serverConfig.load();
    void this.loadGoldenSet();
    void this.loadRuns();
  }

  // ---------------------------------------------------------------- golden set

  private questionGroup(question?: Partial<GoldenQuestion>) {
    return this.formBuilder.group({
      id: this.formBuilder.control(question?.id ?? '', [Validators.required, Validators.maxLength(40)]),
      question: this.formBuilder.control(question?.question ?? '', [Validators.required, Validators.maxLength(2000)]),
      expected_chunk_id: this.formBuilder.control(question?.expected_chunk_id ?? '', [Validators.required, Validators.maxLength(400)]),
      expected_heading: this.formBuilder.control(question?.expected_heading ?? ''),
      exact_token: this.formBuilder.control(question?.exact_token ?? ''),
    });
  }

  async loadGoldenSet(): Promise<void> {
    this.goldenLoading.set(true);
    this.goldenError.set(null);
    try {
      const items = await firstValueFrom(this.api.goldenSet());
      this.setQuestions(items);
    } catch (error) {
      this.goldenError.set(error as ApiError);
    } finally {
      this.goldenLoading.set(false);
    }
  }

  private setQuestions(items: GoldenQuestion[]): void {
    this.questions.clear({ emitEvent: false });
    for (const item of items) {
      this.questions.push(this.questionGroup(item), { emitEvent: false });
    }
    this.goldenDirty.set(false);
  }

  protected addQuestion(): void {
    const next = this.questions.length + 1;
    this.questions.push(this.questionGroup({ id: `Q${next}` }));
    this.goldenDirty.set(true);
    this.tab.set('questions');
  }

  protected removeQuestion(index: number): void {
    this.questions.removeAt(index);
    this.goldenDirty.set(true);
  }

  protected markDirty(): void {
    this.goldenDirty.set(true);
  }

  async saveGoldenSet(): Promise<void> {
    if (this.questions.invalid) {
      this.questions.markAllAsTouched();
      this.notifications.error('Every question needs an id, the question text and an expected chunk id.');
      return;
    }
    this.goldenSaving.set(true);
    try {
      const items = this.questions.getRawValue().map((row) => ({
        id: row.id.trim(),
        question: row.question.trim(),
        expected_chunk_id: row.expected_chunk_id.trim(),
        expected_heading: row.expected_heading.trim() || null,
        exact_token: row.exact_token.trim() || null,
      }));
      const saved = await firstValueFrom(this.api.saveGoldenSet(items));
      this.setQuestions(saved);
      this.notifications.success(`Saved ${saved.length} question${saved.length === 1 ? '' : 's'}`);
    } catch (error) {
      this.notifications.error((error as ApiError).message);
    } finally {
      this.goldenSaving.set(false);
    }
  }

  // ---------------------------------------------------------------------- runs

  async loadRuns(selectLatest = true): Promise<void> {
    this.runsLoading.set(true);
    this.runsError.set(null);
    try {
      const runs = await firstValueFrom(this.api.runs());
      this.runs.set(runs);
      if (selectLatest && runs.length && !this.selectedRun()) {
        await this.selectRun(runs[0].run_id);
      }
    } catch (error) {
      this.runsError.set(error as ApiError);
    } finally {
      this.runsLoading.set(false);
    }
  }

  async selectRun(runId: string): Promise<void> {
    this.selectedRunLoading.set(true);
    this.expandedQuestion.set(null);
    try {
      this.selectedRun.set(await firstValueFrom(this.api.getRun(runId)));
      this.tab.set('results');
    } catch (error) {
      this.notifications.error((error as ApiError).message);
    } finally {
      this.selectedRunLoading.set(false);
    }
  }

  async runEvaluation(): Promise<void> {
    if (this.running()) {
      return;
    }
    this.running.set(true);
    this.runError.set(null);
    try {
      const { mode, label } = this.runForm.getRawValue();
      const run = await firstValueFrom(this.api.run({ mode, top_k: 10, label: label.trim() || null }));
      this.selectedRun.set(run);
      this.runForm.controls.label.reset('');
      this.tab.set('results');
      await this.loadRuns(false);
      this.notifications.success(`Evaluation finished: hit-rate@3 ${(run.hit_rate_at_3 * 100).toFixed(0)}%`);
    } catch (error) {
      this.runError.set(error as ApiError);
    } finally {
      this.running.set(false);
    }
  }

  async confirmDeleteRun(): Promise<void> {
    const run = this.pendingDeleteRun();
    if (!run) {
      return;
    }
    try {
      await firstValueFrom(this.api.deleteRun(run.run_id));
      if (this.selectedRun()?.run_id === run.run_id) {
        this.selectedRun.set(null);
      }
      this.pendingDeleteRun.set(null);
      await this.loadRuns();
    } catch (error) {
      this.notifications.error((error as ApiError).message);
    }
  }

  protected toggleQuestion(id: string): void {
    this.expandedQuestion.update((current) => (current === id ? null : id));
  }

  protected delta(current: number, previous: number | undefined): number | null {
    return previous === undefined ? null : current - previous;
  }

  // ------------------------------------------------------------------- inspect

  async inspect(questionId: string): Promise<void> {
    const run = this.selectedRun();
    this.inspecting.set(questionId);
    this.inspection.set(null);
    this.inspectError.set(null);
    try {
      this.inspection.set(await firstValueFrom(this.api.inspect(questionId, run?.mode ?? 'dense')));
    } catch (error) {
      this.inspectError.set(error as ApiError);
    }
  }

  protected closeInspect(): void {
    this.inspecting.set(null);
    this.inspection.set(null);
    this.inspectError.set(null);
  }

  protected get questionControls() {
    return (this.questions as FormArray).controls as ReturnType<EvaluationPage['questionGroup']>[];
  }
}
