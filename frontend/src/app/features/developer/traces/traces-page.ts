import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { firstValueFrom } from 'rxjs';
import { ApiError, TraceSummary } from '../../../core/models';
import { ServerConfigService } from '../../../core/services/server-config.service';
import { TraceApiService } from '../../../core/services/trace-api.service';
import { EmptyState } from '../../../shared/components/empty-state/empty-state';
import { ErrorState } from '../../../shared/components/error-state/error-state';
import { LoadingIndicator } from '../../../shared/components/loading-indicator/loading-indicator';
import { StatusBadge } from '../../../shared/components/status-badge/status-badge';
import { DurationPipe } from '../../../shared/pipes/duration.pipe';
import { RelativeTimePipe } from '../../../shared/pipes/relative-time.pipe';

const PAGE_SIZE = 25;

@Component({
  selector: 'app-traces-page',
  imports: [FormsModule, RouterLink, EmptyState, ErrorState, LoadingIndicator, StatusBadge, DurationPipe, RelativeTimePipe],
  templateUrl: './traces-page.html',
  styleUrl: './traces-page.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class TracesPage {
  private readonly api = inject(TraceApiService);
  protected readonly serverConfig = inject(ServerConfigService);

  protected readonly items = signal<TraceSummary[]>([]);
  protected readonly total = signal(0);
  protected readonly page = signal(0);
  protected readonly loading = signal(true);
  protected readonly error = signal<ApiError | null>(null);

  protected readonly search = signal('');
  protected readonly outcome = signal<'all' | 'answered' | 'refused'>('all');
  protected readonly mode = signal('');

  protected readonly sampleSeed = signal<number>(new Date().getFullYear() * 10000 + (new Date().getMonth() + 1) * 100 + new Date().getDate());
  protected readonly sampleSize = signal(20);
  protected readonly sample = signal<TraceSummary[] | null>(null);
  protected readonly sampleFrame = signal(0);

  protected readonly pageCount = computed(() => Math.max(1, Math.ceil(this.total() / PAGE_SIZE)));
  protected readonly pageSize = PAGE_SIZE;

  constructor() {
    this.serverConfig.load();
    void this.load();
  }

  async load(): Promise<void> {
    this.loading.set(true);
    this.error.set(null);
    try {
      const response = await firstValueFrom(
        this.api.list({
          limit: PAGE_SIZE,
          offset: this.page() * PAGE_SIZE,
          refused: this.outcome() === 'all' ? null : this.outcome() === 'refused',
          mode: this.mode() || null,
          search: this.search().trim() || null,
        }),
      );
      this.items.set(response.items);
      this.total.set(response.total);
    } catch (error) {
      this.error.set(error as ApiError);
    } finally {
      this.loading.set(false);
    }
  }

  protected applyFilters(): void {
    this.page.set(0);
    void this.load();
  }

  protected goTo(page: number): void {
    this.page.set(Math.max(0, Math.min(this.pageCount() - 1, page)));
    void this.load();
  }

  async drawSample(): Promise<void> {
    try {
      const response = await firstValueFrom(this.api.sample(this.sampleSeed(), this.sampleSize()));
      this.sample.set(response.items);
      this.sampleFrame.set(response.frame);
    } catch (error) {
      this.error.set(error as ApiError);
    }
  }
}
