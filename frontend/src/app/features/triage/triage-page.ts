import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { DecimalPipe, NgTemplateOutlet } from '@angular/common';
import { firstValueFrom } from 'rxjs';
import { ApiError, TriageClaimSummary, TriageRunResponse, TriageSystemResult } from '../../core/models';
import { TriageApiService } from '../../core/services/triage-api.service';
import { NotificationService } from '../../core/services/notification.service';
import { EmptyState } from '../../shared/components/empty-state/empty-state';
import { ErrorState } from '../../shared/components/error-state/error-state';
import { LoadingIndicator } from '../../shared/components/loading-indicator/loading-indicator';
import { PageHeader } from '../../shared/components/page-header/page-header';

@Component({
  selector: 'app-triage-page',
  imports: [DecimalPipe, NgTemplateOutlet, EmptyState, ErrorState, LoadingIndicator, PageHeader],
  templateUrl: './triage-page.html',
  styleUrl: './triage-page.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class TriagePage {
  private readonly api = inject(TriageApiService);
  private readonly notifications = inject(NotificationService);

  protected readonly claims = signal<TriageClaimSummary[]>([]);
  protected readonly claimsLoading = signal(true);
  protected readonly claimsError = signal<ApiError | null>(null);

  protected readonly selectedClaimId = signal<string>('');
  protected readonly running = signal(false);
  protected readonly result = signal<TriageRunResponse | null>(null);
  protected readonly runError = signal<ApiError | null>(null);

  constructor() {
    void this.loadClaims();
  }

  async loadClaims(): Promise<void> {
    this.claimsLoading.set(true);
    this.claimsError.set(null);
    try {
      const claims = await firstValueFrom(this.api.claims());
      this.claims.set(claims);
      if (claims.length && !this.selectedClaimId()) {
        this.selectedClaimId.set(claims[0].claim_id);
      }
    } catch (error) {
      this.claimsError.set(error as ApiError);
    } finally {
      this.claimsLoading.set(false);
    }
  }

  async run(): Promise<void> {
    const claimId = this.selectedClaimId();
    if (!claimId || this.running()) {
      return;
    }
    this.running.set(true);
    this.runError.set(null);
    this.result.set(null);
    try {
      const response = await firstValueFrom(this.api.run({ claim_id: claimId }));
      this.result.set(response);
      if (response.agent.error) {
        this.notifications.error(`Agent run failed: ${response.agent.error}`);
      }
      if (response.workflow.error) {
        this.notifications.error(`Fixed workflow run failed: ${response.workflow.error}`);
      }
    } catch (error) {
      this.runError.set(error as ApiError);
    } finally {
      this.running.set(false);
    }
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

  protected trackStep(_index: number, step: TriageSystemResult['steps'][number]): number {
    return step.step;
  }
}
