import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { DatePipe, DecimalPipe, PercentPipe } from '@angular/common';
import { RouterLink } from '@angular/router';
import { firstValueFrom } from 'rxjs';
import { ApiError, TraceStats, TraceSummary } from '../../core/models';
import { PreferencesStore } from '../../core/services/preferences-store.service';
import { ServerConfigService } from '../../core/services/server-config.service';
import { TraceApiService } from '../../core/services/trace-api.service';
import { EmptyState } from '../../shared/components/empty-state/empty-state';
import { ErrorState } from '../../shared/components/error-state/error-state';
import { LoadingIndicator } from '../../shared/components/loading-indicator/loading-indicator';
import { PageHeader } from '../../shared/components/page-header/page-header';
import { StatusBadge } from '../../shared/components/status-badge/status-badge';
import { DurationPipe } from '../../shared/pipes/duration.pipe';
import { RelativeTimePipe } from '../../shared/pipes/relative-time.pipe';

interface Bar {
  label: string;
  value: number;
  percent: number;
}

@Component({
  selector: 'app-analytics-page',
  imports: [DatePipe, DecimalPipe, PercentPipe, RouterLink, EmptyState, ErrorState, LoadingIndicator, PageHeader, StatusBadge, DurationPipe, RelativeTimePipe],
  templateUrl: './analytics-page.html',
  styleUrl: './analytics-page.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AnalyticsPage {
  private readonly api = inject(TraceApiService);
  protected readonly serverConfig = inject(ServerConfigService);
  protected readonly developerMode = inject(PreferencesStore).developerMode;

  protected readonly stats = signal<TraceStats | null>(null);
  protected readonly recent = signal<TraceSummary[]>([]);
  protected readonly loading = signal(true);
  protected readonly error = signal<ApiError | null>(null);

  protected readonly answeredRate = computed(() => {
    const stats = this.stats();
    return stats && stats.total ? stats.answered / stats.total : 0;
  });

  protected readonly modeBars = computed<Bar[]>(() => toBars(this.stats()?.by_mode ?? {}, (id) => this.serverConfig.modeLabel(id)));
  protected readonly sourceBars = computed<Bar[]>(() => {
    const sources = this.stats()?.top_sources ?? [];
    const max = Math.max(1, ...sources.map((s) => s.citations));
    return sources.map((s) => ({ label: s.source, value: s.citations, percent: (s.citations / max) * 100 }));
  });
  protected readonly dayBars = computed<Bar[]>(() => {
    const days = (this.stats()?.by_day ?? []).slice(-14);
    const max = Math.max(1, ...days.map((d) => d.count));
    return days.map((d) => ({ label: d.day, value: d.count, percent: (d.count / max) * 100 }));
  });
  protected readonly checkBars = computed<Bar[]>(() => {
    const checks = this.stats()?.checks;
    if (!checks) {
      return [];
    }
    return toBars({ Pass: checks.pass, Review: checks.review, Fail: checks.fail }, (label) => label);
  });

  constructor() {
    this.serverConfig.load();
    void this.load();
  }

  async load(): Promise<void> {
    this.loading.set(true);
    this.error.set(null);
    try {
      const [stats, recent] = await Promise.all([
        firstValueFrom(this.api.stats()),
        firstValueFrom(this.api.list({ limit: 8 })),
      ]);
      this.stats.set(stats);
      this.recent.set(recent.items);
    } catch (error) {
      this.error.set(error as ApiError);
    } finally {
      this.loading.set(false);
    }
  }
}

function toBars(counts: Record<string, number>, label: (key: string) => string): Bar[] {
  const entries = Object.entries(counts).sort((a, b) => b[1] - a[1]);
  const max = Math.max(1, ...entries.map(([, value]) => value));
  return entries.map(([key, value]) => ({ label: label(key), value, percent: (value / max) * 100 }));
}
