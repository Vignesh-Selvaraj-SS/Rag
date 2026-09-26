import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { NgTemplateOutlet } from '@angular/common';
import { firstValueFrom } from 'rxjs';
import { ApiError, PolicyQaResponse, PolicyQaStep, PolicyQaSystemChoice } from '../../core/models';
import { PolicyQaApiService } from '../../core/services/policy-qa-api.service';
import { NotificationService } from '../../core/services/notification.service';
import { EmptyState } from '../../shared/components/empty-state/empty-state';
import { ErrorState } from '../../shared/components/error-state/error-state';
import { LoadingIndicator } from '../../shared/components/loading-indicator/loading-indicator';
import { PageHeader } from '../../shared/components/page-header/page-header';

export const SAMPLE_QUESTIONS = [
  'What is the deductible for a water backup claim under HO-2026-01?',
  'Is a dented metal roof covered under HO-2026-08?',
  'A contractor severed a buried water service line - what does subrogation procedure CP-12 require?',
  'A senior field adjuster wants to settle a $120,000 water backup claim - is that within their settlement authority?',
];

@Component({
  selector: 'app-policy-qa-page',
  imports: [NgTemplateOutlet, EmptyState, ErrorState, LoadingIndicator, PageHeader],
  templateUrl: './policy-qa-page.html',
  styleUrl: './policy-qa-page.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class PolicyQaPage {
  private readonly api = inject(PolicyQaApiService);
  private readonly notifications = inject(NotificationService);

  protected readonly samples = SAMPLE_QUESTIONS;
  protected readonly question = signal('');
  protected readonly system = signal<PolicyQaSystemChoice>('both');
  protected readonly running = signal(false);
  protected readonly result = signal<PolicyQaResponse | null>(null);
  protected readonly runError = signal<ApiError | null>(null);

  protected useSample(sample: string): void {
    this.question.set(sample);
  }

  protected onEnter(event: Event): void {
    const keyboard = event as KeyboardEvent;
    if (keyboard.shiftKey) {
      return;
    }
    event.preventDefault();
    void this.ask();
  }

  async ask(): Promise<void> {
    const question = this.question().trim();
    if (!question || this.running()) {
      return;
    }
    this.running.set(true);
    this.runError.set(null);
    this.result.set(null);
    try {
      const response = await firstValueFrom(this.api.ask({ question, system: this.system() }));
      this.result.set(response);
      if (response.agent?.error) {
        this.notifications.error(`Agent run failed: ${response.agent.error}`);
      }
      if (response.workflow?.error) {
        this.notifications.error(`Fixed workflow run failed: ${response.workflow.error}`);
      }
    } catch (error) {
      this.runError.set(error as ApiError);
    } finally {
      this.running.set(false);
    }
  }

  protected retry(): void {
    void this.ask();
  }

  protected pretty(value: unknown): string {
    if (value === null || value === undefined) {
      return '—';
    }
    return JSON.stringify(value, null, 2);
  }

  protected trackStep(_index: number, step: PolicyQaStep): number {
    return step.step;
  }
}
