import { Pipe, PipeTransform } from '@angular/core';

/** Milliseconds as a short human duration: 850 ms, 2.3 s, 1m 05s. */
@Pipe({ name: 'duration' })
export class DurationPipe implements PipeTransform {
  transform(ms: number | null | undefined): string {
    if (ms === null || ms === undefined || Number.isNaN(ms)) {
      return '—';
    }
    if (ms < 1000) {
      return `${Math.round(ms)} ms`;
    }
    if (ms < 60_000) {
      return `${(ms / 1000).toFixed(1)} s`;
    }
    const minutes = Math.floor(ms / 60_000);
    const seconds = Math.round((ms % 60_000) / 1000);
    return `${minutes}m ${String(seconds).padStart(2, '0')}s`;
  }
}
