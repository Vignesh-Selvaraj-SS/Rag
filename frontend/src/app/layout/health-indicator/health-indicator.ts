import { ChangeDetectionStrategy, Component, DestroyRef, computed, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { switchMap, timer } from 'rxjs';
import { HealthResponse } from '../../core/models';
import { SettingsApiService } from '../../core/services/settings-api.service';

const POLL_MS = 30_000;

/** Small "API · index · model" status line in the sidebar footer, polled every 30 s. */
@Component({
  selector: 'app-health-indicator',
  template: `
    <div class="health" [title]="tooltip()">
      <span class="health__dot" [class]="'health__dot health__dot--' + tone()" aria-hidden="true"></span>
      <span class="small muted">{{ label() }}</span>
    </div>
  `,
  styles: `
    .health {
      display: flex;
      align-items: center;
      gap: 8px;
    }
    .health__dot {
      width: 8px;
      height: 8px;
      border-radius: 50%;
      background: var(--text-faint);
      flex-shrink: 0;
    }
    .health__dot--ok {
      background: var(--success);
    }
    .health__dot--warn {
      background: var(--warning);
    }
    .health__dot--down {
      background: var(--danger);
    }
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class HealthIndicator {
  private readonly api = inject(SettingsApiService);
  private readonly destroyRef = inject(DestroyRef);

  private readonly health = signal<HealthResponse | null>(null);
  private readonly unreachable = signal(false);

  protected readonly tone = computed(() => {
    if (this.unreachable()) {
      return 'down';
    }
    const health = this.health();
    if (!health) {
      return 'unknown';
    }
    return health.index_ready && health.llm_configured ? 'ok' : 'warn';
  });

  protected readonly label = computed(() => {
    if (this.unreachable()) {
      return 'API unreachable';
    }
    const health = this.health();
    if (!health) {
      return 'Checking…';
    }
    if (!health.index_ready) {
      return 'Index empty';
    }
    if (!health.llm_configured) {
      return 'Model key missing';
    }
    return `Ready · ${health.index_chunks.toLocaleString()} chunks`;
  });

  protected readonly tooltip = computed(() => {
    const health = this.health();
    return health ? `API ${health.version} · ${health.index_chunks} chunks indexed` : '';
  });

  constructor() {
    timer(0, POLL_MS)
      .pipe(
        switchMap(() => this.api.health()),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe({
        next: (health) => {
          this.health.set(health);
          this.unreachable.set(false);
        },
        error: () => this.unreachable.set(true),
      });
  }
}
