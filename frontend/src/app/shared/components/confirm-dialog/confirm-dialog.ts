import {
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  effect,
  input,
  output,
  viewChild,
} from '@angular/core';

/**
 * Native <dialog>-based confirmation. Opened/closed through the `open` input
 * so the parent owns the state; `confirmed` fires only on the primary button.
 */
@Component({
  selector: 'app-confirm-dialog',
  template: `
    <dialog #dialog class="dialog" (close)="cancelled.emit()" (cancel)="onCancel($event)">
      <form method="dialog" (submit)="$event.preventDefault()">
        <h2 class="dialog__title">{{ title() }}</h2>
        <p class="dialog__message">{{ message() }}</p>
        <div class="dialog__actions">
          <button type="button" class="btn" (click)="cancelled.emit()">Cancel</button>
          <button
            type="button"
            class="btn"
            [class.btn--danger]="destructive()"
            [class.btn--primary]="!destructive()"
            [disabled]="busy()"
            (click)="confirmed.emit()"
          >
            {{ busy() ? 'Working…' : confirmLabel() }}
          </button>
        </div>
      </form>
    </dialog>
  `,
  styles: `
    .dialog {
      border: 1px solid var(--border);
      border-radius: var(--radius-lg);
      background: var(--bg-elevated);
      color: var(--text);
      padding: 22px 24px;
      width: min(440px, calc(100vw - 32px));
      box-shadow: var(--shadow-lg);
    }
    .dialog::backdrop {
      background: rgb(0 0 0 / 0.4);
    }
    .dialog__title {
      margin-bottom: 8px;
    }
    .dialog__message {
      color: var(--text-muted);
      font-size: 0.95rem;
    }
    .dialog__actions {
      display: flex;
      justify-content: flex-end;
      gap: 8px;
      margin-top: 20px;
    }
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ConfirmDialog {
  readonly open = input(false);
  readonly title = input('Are you sure?');
  readonly message = input('');
  readonly confirmLabel = input('Confirm');
  readonly destructive = input(false);
  readonly busy = input(false);

  readonly confirmed = output<void>();
  readonly cancelled = output<void>();

  private readonly dialog = viewChild.required<ElementRef<HTMLDialogElement>>('dialog');

  constructor() {
    effect(() => {
      const element = this.dialog().nativeElement;
      if (this.open() && !element.open) {
        element.showModal();
      } else if (!this.open() && element.open) {
        element.close();
      }
    });
  }

  protected onCancel(event: Event): void {
    event.preventDefault();
    this.cancelled.emit();
  }
}
