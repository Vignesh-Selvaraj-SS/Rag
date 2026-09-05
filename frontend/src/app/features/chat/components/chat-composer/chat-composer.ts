import { ChangeDetectionStrategy, Component, ElementRef, input, output, signal, viewChild } from '@angular/core';
import { FormsModule } from '@angular/forms';

const MAX_LENGTH = 2000;

@Component({
  selector: 'app-chat-composer',
  imports: [FormsModule],
  template: `
    <form class="composer" (submit)="submit($event)">
      <label class="visually-hidden" for="question">Your question</label>
      <textarea
        #box
        id="question"
        class="composer__input"
        rows="1"
        placeholder="Ask about your documents…"
        [attr.maxlength]="maxLength"
        [(ngModel)]="text"
        name="question"
        [disabled]="disabled()"
        (keydown.enter)="onEnter($event)"
        (input)="autosize()"
      ></textarea>
      <div class="composer__side">
        <span class="faint small composer__count" [class.composer__count--warn]="text().length > maxLength * 0.9">
          {{ text().length }}/{{ maxLength }}
        </span>
        <button type="submit" class="btn btn--primary" [disabled]="disabled() || !text().trim()">
          {{ disabled() ? 'Answering…' : 'Ask' }}
        </button>
      </div>
    </form>
    <p class="faint small composer__hint">Enter to send · Shift+Enter for a new line</p>
  `,
  styles: `
    .composer {
      display: flex;
      align-items: flex-end;
      gap: 10px;
      padding: 10px 10px 10px 14px;
      border: 1px solid var(--border-strong);
      border-radius: var(--radius-lg);
      background: var(--bg-elevated);
    }
    .composer:focus-within {
      border-color: var(--accent);
      box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent) 18%, transparent);
    }
    .composer__input {
      flex: 1;
      border: none;
      background: transparent;
      resize: none;
      padding: 6px 0;
      max-height: 180px;
      line-height: 1.45;
      font-size: 0.95rem;
    }
    .composer__input:focus {
      outline: none;
    }
    .composer__side {
      display: flex;
      align-items: center;
      gap: 10px;
    }
    .composer__count--warn {
      color: var(--warning);
    }
    .composer__hint {
      margin: 6px 4px 0;
    }
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ChatComposer {
  readonly disabled = input(false);
  readonly submitted = output<string>();

  protected readonly maxLength = MAX_LENGTH;
  protected readonly text = signal('');

  private readonly box = viewChild.required<ElementRef<HTMLTextAreaElement>>('box');

  protected submit(event?: Event): void {
    event?.preventDefault();
    const value = this.text().trim();
    if (!value || this.disabled()) {
      return;
    }
    this.submitted.emit(value);
    this.text.set('');
    this.autosize();
    this.box().nativeElement.focus();
  }

  protected onEnter(event: Event): void {
    const keyboard = event as KeyboardEvent;
    if (keyboard.shiftKey) {
      return;
    }
    this.submit(event);
  }

  protected autosize(): void {
    const element = this.box().nativeElement;
    element.style.height = 'auto';
    element.style.height = `${Math.min(element.scrollHeight, 180)}px`;
  }
}
