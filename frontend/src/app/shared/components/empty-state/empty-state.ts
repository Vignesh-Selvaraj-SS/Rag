import { ChangeDetectionStrategy, Component, input } from '@angular/core';

@Component({
  selector: 'app-empty-state',
  template: `
    <div class="empty">
      @if (icon()) {
        <div class="empty__icon" aria-hidden="true">{{ icon() }}</div>
      }
      <h3 class="empty__title">{{ title() }}</h3>
      @if (description()) {
        <p class="empty__description">{{ description() }}</p>
      }
      <div class="empty__actions"><ng-content /></div>
    </div>
  `,
  styles: `
    .empty {
      display: flex;
      flex-direction: column;
      align-items: center;
      text-align: center;
      gap: 8px;
      padding: 40px 20px;
      color: var(--text-muted);
    }
    .empty__icon {
      font-size: 2rem;
      opacity: 0.7;
    }
    .empty__title {
      color: var(--text);
    }
    .empty__description {
      max-width: 420px;
      font-size: 0.9rem;
    }
    .empty__actions {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      justify-content: center;
      margin-top: 6px;
    }
    .empty__actions:empty {
      display: none;
    }
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class EmptyState {
  readonly title = input.required<string>();
  readonly description = input<string>('');
  readonly icon = input<string>('');
}
