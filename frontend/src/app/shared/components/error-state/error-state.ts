import { ChangeDetectionStrategy, Component, inject, input, output } from '@angular/core';
import { ApiError } from '../../../core/models';
import { PreferencesStore } from '../../../core/services/preferences-store.service';

/**
 * Friendly error block with a Retry button. In Developer mode the technical
 * details (status, request id, backend detail) are shown underneath.
 */
@Component({
  selector: 'app-error-state',
  template: `
    <div class="error" role="alert">
      <div class="error__body">
        <strong class="error__title">{{ title() }}</strong>
        <p class="error__message">{{ error()?.message ?? 'Something went wrong.' }}</p>
        @if (developerMode() && error(); as err) {
          <dl class="error__details mono">
            <dt>Status</dt>
            <dd>{{ err.status || 'network' }}</dd>
            @if (err.requestId) {
              <dt>Request</dt>
              <dd>{{ err.requestId }}</dd>
            }
            @if (err.detail && err.detail !== err.message) {
              <dt>Detail</dt>
              <dd>{{ err.detail }}</dd>
            }
            @if (err.url) {
              <dt>URL</dt>
              <dd class="truncate">{{ err.url }}</dd>
            }
          </dl>
        }
      </div>
      @if (retryable()) {
        <button type="button" class="btn btn--sm" (click)="retry.emit()">Retry</button>
      }
    </div>
  `,
  styles: `
    .error {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 16px;
      padding: 14px 16px;
      border: 1px solid color-mix(in srgb, var(--danger) 40%, transparent);
      background: var(--danger-soft);
      border-radius: var(--radius);
    }
    .error__body {
      display: flex;
      flex-direction: column;
      gap: 2px;
      min-width: 0;
    }
    .error__title {
      color: var(--danger);
    }
    .error__message {
      font-size: 0.9rem;
    }
    .error__details {
      display: grid;
      grid-template-columns: max-content 1fr;
      gap: 2px 12px;
      margin: 8px 0 0;
      font-size: 0.78rem;
      color: var(--text-muted);
    }
    .error__details dd {
      margin: 0;
      min-width: 0;
    }
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ErrorState {
  readonly title = input('Something went wrong');
  readonly error = input<ApiError | null>(null);
  readonly retryable = input(true);
  readonly retry = output<void>();

  protected readonly developerMode = inject(PreferencesStore).developerMode;
}
