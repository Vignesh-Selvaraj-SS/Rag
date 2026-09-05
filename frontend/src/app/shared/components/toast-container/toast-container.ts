import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { NotificationService } from '../../../core/services/notification.service';

@Component({
  selector: 'app-toast-container',
  template: `
    <div class="toasts" aria-live="polite" aria-atomic="false">
      @for (toast of notifications.toasts(); track toast.id) {
        <div class="toast" [class]="'toast toast--' + toast.kind" role="status">
          <span>{{ toast.message }}</span>
          <button type="button" class="toast__close" aria-label="Dismiss" (click)="notifications.dismiss(toast.id)">
            ×
          </button>
        </div>
      }
    </div>
  `,
  styles: `
    .toasts {
      position: fixed;
      right: 16px;
      bottom: 16px;
      display: flex;
      flex-direction: column;
      gap: 8px;
      z-index: 1000;
      max-width: min(380px, calc(100vw - 32px));
    }
    .toast {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 12px;
      padding: 10px 12px 10px 14px;
      border-radius: var(--radius);
      border: 1px solid var(--border);
      border-left-width: 4px;
      background: var(--bg-elevated);
      box-shadow: var(--shadow);
      font-size: 0.9rem;
      animation: fade-in 0.2s ease both;
    }
    .toast--success {
      border-left-color: var(--success);
    }
    .toast--error {
      border-left-color: var(--danger);
    }
    .toast--info {
      border-left-color: var(--info);
    }
    .toast__close {
      border: none;
      background: transparent;
      color: var(--text-muted);
      font-size: 1.1rem;
      line-height: 1;
      cursor: pointer;
      padding: 0 2px;
    }
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ToastContainer {
  protected readonly notifications = inject(NotificationService);
}
