import { TestBed } from '@angular/core/testing';
import { MarkdownService } from './markdown.service';

describe('MarkdownService', () => {
  let service: MarkdownService;

  beforeEach(() => {
    TestBed.configureTestingModule({});
    service = TestBed.inject(MarkdownService);
  });

  it('renders markdown', () => {
    const html = service.render('**bold** and `code`');
    expect(html).toContain('<strong>bold</strong>');
    expect(html).toContain('<code>code</code>');
  });

  it('turns citation tags into chips and marks out-of-range tags invalid', () => {
    const html = service.render('Fact [S1]. Other [S9].', 2);
    expect(html).toContain('data-cite="1"');
    expect(html).toContain('class="cite"');
    expect(html).toContain('cite--invalid');
    expect(html).toContain('data-cite="9"');
  });

  it('strips scripts, event handlers and javascript: links', () => {
    const html = service.render('<img src=x onerror="alert(1)"><script>alert(1)</script>[link](javascript:alert(1)) <a href="https://x.test" onclick="x()">ok</a>');
    expect(html).not.toContain('<script');
    expect(html).not.toContain('onerror');
    expect(html).not.toContain('onclick');
    expect(html).not.toContain('javascript:');
    expect(html).toContain('href="https://x.test"');
    expect(html).toContain('rel="noopener noreferrer"');
  });

  it('does not allow arbitrary data attributes or unknown tags', () => {
    const html = service.render('<div data-evil="1"><iframe src="https://x"></iframe>text</div>');
    expect(html).not.toContain('iframe');
    expect(html).not.toContain('data-evil');
    expect(html).toContain('text');
  });
});
