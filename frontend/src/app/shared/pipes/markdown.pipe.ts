import { Pipe, PipeTransform, inject } from '@angular/core';
import { DomSanitizer, SafeHtml } from '@angular/platform-browser';
import { MarkdownService } from '../services/markdown.service';

/**
 * Render an answer as sanitised HTML with `[S#]` citation chips.
 * The output is sanitised by DOMPurify before being marked trusted, so
 * bypassing Angular's sanitizer here does not admit unsafe markup.
 */
@Pipe({ name: 'markdown' })
export class MarkdownPipe implements PipeTransform {
  private readonly markdown = inject(MarkdownService);
  private readonly sanitizer = inject(DomSanitizer);

  transform(value: string | null | undefined, sourceCount = Number.POSITIVE_INFINITY): SafeHtml {
    return this.sanitizer.bypassSecurityTrustHtml(this.markdown.render(value ?? '', sourceCount));
  }
}
