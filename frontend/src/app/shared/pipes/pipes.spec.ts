import { DurationPipe } from './duration.pipe';
import { FileSizePipe } from './file-size.pipe';
import { RelativeTimePipe } from './relative-time.pipe';

describe('FileSizePipe', () => {
  const pipe = new FileSizePipe();

  it('formats bytes', () => {
    expect(pipe.transform(512)).toBe('512 B');
    expect(pipe.transform(2048)).toBe('2.0 KB');
    expect(pipe.transform(15 * 1024 * 1024)).toBe('15 MB');
    expect(pipe.transform(null)).toBe('—');
  });
});

describe('DurationPipe', () => {
  const pipe = new DurationPipe();

  it('formats milliseconds', () => {
    expect(pipe.transform(850)).toBe('850 ms');
    expect(pipe.transform(2340)).toBe('2.3 s');
    expect(pipe.transform(65_000)).toBe('1m 05s');
    expect(pipe.transform(undefined)).toBe('—');
  });
});

describe('RelativeTimePipe', () => {
  const pipe = new RelativeTimePipe();
  const now = new Date('2026-09-04T12:00:00Z');

  it('formats relative times', () => {
    expect(pipe.transform('2026-09-04T11:59:50Z', now)).toBe('just now');
    expect(pipe.transform('2026-09-04T11:30:00Z', now)).toBe('30 minutes ago');
    expect(pipe.transform('2026-09-02T12:00:00Z', now)).toBe('2 days ago');
    expect(pipe.transform(null, now)).toBe('—');
    expect(pipe.transform('garbage', now)).toBe('—');
  });
});
