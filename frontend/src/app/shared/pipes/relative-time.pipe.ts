import { Pipe, PipeTransform } from '@angular/core';

const UNITS: [Intl.RelativeTimeFormatUnit, number][] = [
  ['year', 365 * 24 * 3600],
  ['month', 30 * 24 * 3600],
  ['day', 24 * 3600],
  ['hour', 3600],
  ['minute', 60],
];

@Pipe({ name: 'relativeTime' })
export class RelativeTimePipe implements PipeTransform {
  private readonly formatter = new Intl.RelativeTimeFormat(undefined, { numeric: 'auto' });

  transform(value: string | Date | null | undefined, now: Date = new Date()): string {
    if (!value) {
      return '—';
    }
    const date = value instanceof Date ? value : new Date(value);
    if (Number.isNaN(date.getTime())) {
      return '—';
    }
    const seconds = Math.round((date.getTime() - now.getTime()) / 1000);
    for (const [unit, size] of UNITS) {
      if (Math.abs(seconds) >= size) {
        return this.formatter.format(Math.round(seconds / size), unit);
      }
    }
    return Math.abs(seconds) < 45 ? 'just now' : this.formatter.format(seconds, 'second');
  }
}
