import { Injectable, computed, inject, signal } from '@angular/core';
import { ApiError, AppSettings, ChunkStrategyInfo, RetrievalModeInfo } from '../models';
import { SettingsApiService } from './settings-api.service';

/**
 * Signal view of the server's configuration (modes, strategies, defaults).
 * Loaded once on first use; every page reads from here instead of calling
 * the API again.
 */
@Injectable({ providedIn: 'root' })
export class ServerConfigService {
  private readonly api = inject(SettingsApiService);

  private readonly state = signal<AppSettings | null>(null);
  private readonly loadError = signal<ApiError | null>(null);
  private loading = false;

  readonly settings = this.state.asReadonly();
  readonly error = this.loadError.asReadonly();
  readonly modes = computed<RetrievalModeInfo[]>(() => this.state()?.modes ?? []);
  readonly strategies = computed<ChunkStrategyInfo[]>(() => this.state()?.strategies ?? []);
  readonly llmConfigured = computed(() => this.state()?.generation.configured ?? true);
  readonly defaults = computed(() => this.state()?.defaults ?? { mode: 'dense' as const, top_k: 5, min_score: 0.6 });

  load(force = false): void {
    if ((this.state() && !force) || this.loading) {
      return;
    }
    this.loading = true;
    this.api.settings(force).subscribe({
      next: (settings) => {
        this.state.set(settings);
        this.loadError.set(null);
        this.loading = false;
      },
      error: (error: ApiError) => {
        this.loadError.set(error);
        this.loading = false;
      },
    });
  }

  modeLabel(id: string | null | undefined): string {
    return this.modes().find((mode) => mode.id === id)?.label ?? id ?? '';
  }

  strategyLabel(id: string | null | undefined): string {
    return this.strategies().find((strategy) => strategy.id === id)?.label ?? id ?? '';
  }
}
