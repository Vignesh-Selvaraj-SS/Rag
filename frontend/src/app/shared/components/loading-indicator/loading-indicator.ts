import { ChangeDetectionStrategy, Component, input } from '@angular/core';

@Component({
  selector: 'app-loading-indicator',
  template: `
    <div class="loading" [class.loading--inline]="inline()" role="status" aria-live="polite">
      <span class="loading__spinner" aria-hidden="true"></span>
      <span>{{ message() }}</span>
    </div>
  `,
  styles: `
    .loading {
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 10px;
      padding: 32px;
      color: var(--text-muted);
      font-size: 0.9rem;
    }
    .loading--inline {
      padding: 0;
      justify-content: flex-start;
    }
    .loading__spinner {
      width: 16px;
      height: 16px;
      border-radius: 50%;
      border: 2px solid var(--border-strong);
      border-top-color: var(--accent);
      animation: spin 0.8s linear infinite;
    }
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class LoadingIndicator {
  readonly message = input('Loading…');
  readonly inline = input(false);
}
