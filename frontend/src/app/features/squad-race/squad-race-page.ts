import { ChangeDetectionStrategy, Component, DestroyRef, inject, signal } from '@angular/core';
import { DecimalPipe, PercentPipe } from '@angular/common';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { firstValueFrom } from 'rxjs';
import { switchMap, timer } from 'rxjs';
import { ApiError, SquadRaceStatusResponse } from '../../core/models';
import { SquadApiService } from '../../core/services/squad-api.service';
import { NotificationService } from '../../core/services/notification.service';
import { PageHeader } from '../../shared/components/page-header/page-header';

const POLL_MS = 2_000;

@Component({
  selector: 'app-squad-race-page',
  imports: [DecimalPipe, PercentPipe, PageHeader],
  templateUrl: './squad-race-page.html',
  styleUrl: './squad-race-page.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class SquadRacePage {
  private readonly api = inject(SquadApiService);
  private readonly notifications = inject(NotificationService);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly status = signal<SquadRaceStatusResponse | null>(null);
  protected readonly starting = signal(false);
  protected readonly unreachable = signal(false);

  constructor() {
    timer(0, POLL_MS)
      .pipe(
        switchMap(() => this.api.raceStatus()),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe({
        next: (status) => {
          this.status.set(status);
          this.unreachable.set(false);
        },
        error: () => this.unreachable.set(true),
      });
  }

  async startRace(): Promise<void> {
    if (this.starting() || this.status()?.running) {
      return;
    }
    this.starting.set(true);
    try {
      const status = await firstValueFrom(this.api.startRace({ sleep: 5.0 }));
      this.status.set(status);
    } catch (error) {
      const apiError = error as ApiError;
      this.notifications.error(`Could not start the race: ${apiError.message || 'unknown error'}`);
    } finally {
      this.starting.set(false);
    }
  }

  protected progressPct(status: SquadRaceStatusResponse): number {
    return status.total_pairs ? Math.round((status.completed_pairs / status.total_pairs) * 100) : 0;
  }

  protected statusClass(value: string | null): string {
    if (value === 'pass') return 'cell cell--pass';
    if (value === 'fail') return 'cell cell--fail';
    if (value === 'review') return 'cell cell--review';
    return 'cell cell--pending';
  }

  protected sortedHandoffs(totals: Record<string, number>): { key: string; tokens: number; pct: number }[] {
    const entries = Object.entries(totals);
    const grandTotal = entries.reduce((sum, [, tokens]) => sum + tokens, 0);
    return entries
      .map(([key, tokens]) => ({ key, tokens, pct: grandTotal ? Math.round((tokens / grandTotal) * 100) : 0 }))
      .sort((a, b) => b.tokens - a.tokens);
  }
}
