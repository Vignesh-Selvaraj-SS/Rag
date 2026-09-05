import { Injectable } from '@angular/core';
import DOMPurify from 'dompurify';
import { marked } from 'marked';

const CITATION = /\[S(\d+)\]/g;

/**
 * Markdown → safe HTML. Answers come from a language model, so everything
 * goes through DOMPurify; only a conservative tag/attribute allow-list
 * survives. Citation tags `[S3]` become <button data-cite="3"> chips that the
 * chat message component turns into source highlights.
 */
@Injectable({ providedIn: 'root' })
export class MarkdownService {
  private readonly purifier = DOMPurify();

  constructor() {
    marked.setOptions({ gfm: true, breaks: true });
    this.purifier.setConfig({
      ALLOWED_TAGS: [
        'p', 'br', 'strong', 'em', 'b', 'i', 'u', 's', 'del', 'code', 'pre', 'blockquote',
        'ul', 'ol', 'li', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'a', 'hr',
        'table', 'thead', 'tbody', 'tr', 'th', 'td', 'span', 'button',
      ],
      ALLOWED_ATTR: ['href', 'title', 'class', 'data-cite', 'type', 'aria-label'],
      ALLOW_DATA_ATTR: false,
      ADD_ATTR: ['target', 'rel'],
    });
    // External links open in a new tab without giving the opener away.
    this.purifier.addHook('afterSanitizeAttributes', (node) => {
      if (node.tagName === 'A' && node.getAttribute('href')) {
        const href = node.getAttribute('href') ?? '';
        if (!/^(https?:|mailto:)/i.test(href)) {
          node.removeAttribute('href');
          return;
        }
        node.setAttribute('target', '_blank');
        node.setAttribute('rel', 'noopener noreferrer');
      }
    });
  }

  render(markdown: string, sourceCount = Number.POSITIVE_INFINITY): string {
    const html = marked.parse(markdown, { async: false });
    const withCitations = html.replace(CITATION, (_match, number: string) => {
      const index = Number(number);
      const invalid = index < 1 || index > sourceCount;
      return `<button type="button" class="cite${invalid ? ' cite--invalid' : ''}" data-cite="${index}" aria-label="Source ${index}${invalid ? ' (not provided)' : ''}">S${index}</button>`;
    });
    return this.purifier.sanitize(withCitations);
  }

  /** Plain text version for clipboard copies. */
  toPlainText(markdown: string): string {
    return markdown.replace(/\r/g, '').trim();
  }
}
