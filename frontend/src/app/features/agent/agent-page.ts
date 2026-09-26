import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { DecimalPipe, NgTemplateOutlet } from '@angular/common';
import { firstValueFrom } from 'rxjs';
import { AgentClaimSummary, AgentRunResponse, AgentStep, AgentSystemChoice, ApiError } from '../../core/models';
import { AgentApiService } from '../../core/services/agent-api.service';
import { NotificationService } from '../../core/services/notification.service';
import { EmptyState } from '../../shared/components/empty-state/empty-state';
import { ErrorState } from '../../shared/components/error-state/error-state';
import { LoadingIndicator } from '../../shared/components/loading-indicator/loading-indicator';
import { PageHeader } from '../../shared/components/page-header/page-header';

export const SAMPLE_QUESTIONS = [
  'What is the deductible for a water backup claim under HO-2026-01?',
  'Is a dented metal roof covered under HO-2026-08?',
  'A contractor severed a buried water service line - what does subrogation procedure CP-12 require?',
];

@Component({
  selector: 'app-agent-page',
  imports: [DecimalPipe, NgTemplateOutlet, EmptyState, ErrorState, LoadingIndicator, PageHeader],
  templateUrl: './agent-page.html',
  styleUrl: './agent-page.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AgentPage {
  private readonly api = inject(AgentApiService);
  private readonly notifications = inject(NotificationService);

  protected readonly samples = SAMPLE_QUESTIONS;
  protected readonly claims = signal<AgentClaimSummary[]>([]);
  protected readonly claimsLoading = signal(true);

  protected readonly userInput = signal('');
  protected readonly system = signal<AgentSystemChoice>('both');
  protected readonly running = signal(false);
  protected readonly result = signal<AgentRunResponse | null>(null);
  protected readonly runError = signal<ApiError | null>(null);

  constructor() {
    void this.loadClaims();
  }

  async loadClaims(): Promise<void> {
    this.claimsLoading.set(true);
    try {
      this.claims.set(await firstValueFrom(this.api.claims()));
    } catch {
      // Claim-id chips are a convenience, not required to use the page - a
      // failed fetch here shouldn't block asking a free-text question.
      this.claims.set([]);
    } finally {
      this.claimsLoading.set(false);
    }
  }

  protected useSample(sample: string): void {
    this.userInput.set(sample);
  }

  protected onEnter(event: Event): void {
    const keyboard = event as KeyboardEvent;
    if (keyboard.shiftKey) {
      return;
    }
    event.preventDefault();
    void this.run();
  }

  async run(): Promise<void> {
    const userInput = this.userInput().trim();
    if (!userInput || this.running()) {
      return;
    }
    this.running.set(true);
    this.runError.set(null);
    this.result.set(null);
    try {
      const response = await firstValueFrom(this.api.run({ user_input: userInput, system: this.system() }));
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
    void this.run();
  }

  protected decisionClass(decision: string | null): string {
    switch (decision) {
      case 'approved':
        return 'decision decision--approved';
      case 'denied':
        return 'decision decision--denied';
      case 'partial':
        return 'decision decision--partial';
      case 'escalated':
        return 'decision decision--escalated';
      default:
        return 'decision decision--unknown';
    }
  }

  protected pretty(value: unknown): string {
    if (value === null || value === undefined) {
      return '—';
    }
    return JSON.stringify(value, null, 2);
  }

  protected trackStep(_index: number, step: AgentStep): number {
    return step.step;
  }
}
