import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';

export type BadgeTone = 'neutral' | 'success' | 'warning' | 'danger' | 'info' | 'accent';

const TONE_BY_STATUS: Record<string, BadgeTone> = {
  indexed: 'success',
  pending: 'warning',
  removed: 'danger',
  pass: 'success',
  review: 'warning',
  fail: 'danger',
  skip: 'neutral',
  answered: 'success',
  refused: 'warning',
  gate: 'neutral',
  model: 'warning',
  hit: 'success',
  miss: 'danger',
};

const LABEL_BY_STATUS: Record<string, string> = {
  indexed: 'Indexed',
  pending: 'Needs rebuild',
  removed: 'File removed',
  pass: 'Pass',
  review: 'Review',
  fail: 'Fail',
  skip: 'Not applicable',
  gate: 'Refused by gate',
  model: 'Refused by model',
};

@Component({
  selector: 'app-status-badge',
  template: `<span class="badge" [class]="'badge badge--' + tone()">{{ text() }}</span>`,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class StatusBadge {
  readonly status = input.required<string>();
  readonly label = input<string | null>(null);

  protected readonly tone = computed(() => TONE_BY_STATUS[this.status()] ?? 'neutral');
  protected readonly text = computed(() => this.label() ?? LABEL_BY_STATUS[this.status()] ?? this.status());
}
