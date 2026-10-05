import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { DecimalPipe } from '@angular/common';
import { firstValueFrom } from 'rxjs';
import { ApiError, SquadRunResponse } from '../../core/models';
import { SquadApiService } from '../../core/services/squad-api.service';
import { NotificationService } from '../../core/services/notification.service';
import { EmptyState } from '../../shared/components/empty-state/empty-state';
import { ErrorState } from '../../shared/components/error-state/error-state';
import { LoadingIndicator } from '../../shared/components/loading-indicator/loading-indicator';
import { PageHeader } from '../../shared/components/page-header/page-header';

export const SAMPLE_NOTES = [
  'Claim CLM-2026-00417, date of loss 2026-03-14. Policyholder reports the finished basement flooded after the sump pump stopped during a storm. Carpet, drywall and a chest freezer damaged. Dwelling built 2015, basement finished 2019. Endorsement HO-2026-01 is attached. What is the coverage position and the deductible?',
  'Claim CLM-2026-00892, date of loss 2026-04-02. Insured reports a credit card was opened in her name and a loan application was submitted. She has filed a police report. Endorsement HO-2026-07 is attached. Confirm the coverage position and the deductible that applies.',
  'Claim CLM-2026-01133, date of loss 2026-05-19. A scheduled diamond ring, appraised and listed on the schedule under endorsement HO-2026-04, was lost while the insured was travelling abroad. Confirm the settlement basis and what deductible applies.',
];

const FIELD_ORDER = ['CLAIM', 'DATE OF LOSS', 'COVERAGE', 'BASIS', 'DEDUCTIBLE', 'NEXT ACTION'];

@Component({
  selector: 'app-squad-page',
  imports: [DecimalPipe, EmptyState, ErrorState, LoadingIndicator, PageHeader],
  templateUrl: './squad-page.html',
  styleUrl: './squad-page.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class SquadPage {
  private readonly api = inject(SquadApiService);
  private readonly notifications = inject(NotificationService);

  protected readonly samples = SAMPLE_NOTES;
  protected readonly fieldOrder = FIELD_ORDER;

  protected readonly notes = signal('');
  protected readonly simulateFailure = signal(false);
  protected readonly running = signal(false);
  protected readonly result = signal<SquadRunResponse | null>(null);
  protected readonly runError = signal<ApiError | null>(null);
  protected readonly showTrace = signal(false);

  protected useSample(sample: string): void {
    this.notes.set(sample);
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
    const notes = this.notes().trim();
    if (!notes || this.running()) {
      return;
    }
    this.running.set(true);
    this.runError.set(null);
    this.result.set(null);
    try {
      const response = await firstValueFrom(
        this.api.run({ notes, simulate_coverage_worker_failure: this.simulateFailure() }),
      );
      this.result.set(response);
      if (response.error) {
        this.notifications.error(`Squad run failed: ${response.error}`);
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

  protected coverageClass(coverage: string | null): string {
    const value = (coverage || '').toLowerCase();
    if (value === 'covered') return 'decision decision--approved';
    if (value === 'denied') return 'decision decision--denied';
    if (value === 'partially covered') return 'decision decision--partial';
    if (value.includes('not established')) return 'decision decision--escalated';
    return 'decision decision--unknown';
  }

  protected toggleTrace(): void {
    this.showTrace.set(!this.showTrace());
  }
}
