import { ChangeDetectionStrategy, Component, computed, inject, input, signal } from '@angular/core';
import { DatePipe } from '@angular/common';
import { NotificationService } from '../../../../core/services/notification.service';
import { PreferencesStore } from '../../../../core/services/preferences-store.service';
import { ServerConfigService } from '../../../../core/services/server-config.service';
import { ErrorState } from '../../../../shared/components/error-state/error-state';
import { MarkdownPipe } from '../../../../shared/pipes/markdown.pipe';
import { DurationPipe } from '../../../../shared/pipes/duration.pipe';
import { MarkdownService } from '../../../../shared/services/markdown.service';
import { ChatMessage, ChatStore } from '../../chat-store.service';
import { RetrievalDetails } from '../retrieval-details/retrieval-details';

@Component({
  selector: 'app-chat-message',
  imports: [DatePipe, MarkdownPipe, DurationPipe, ErrorState, RetrievalDetails],
  templateUrl: './chat-message.html',
  styleUrl: './chat-message.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ChatMessageItem {
  readonly message = input.required<ChatMessage>();

  private readonly store = inject(ChatStore);
  private readonly notifications = inject(NotificationService);
  private readonly markdown = inject(MarkdownService);
  protected readonly serverConfig = inject(ServerConfigService);
  protected readonly developerMode = inject(PreferencesStore).developerMode;

  protected readonly highlightedSource = signal<number | null>(null);
  protected readonly showDetails = signal(false);

  protected readonly assistant = computed(() => {
    const message = this.message();
    return message.role === 'assistant' ? message : null;
  });

  protected readonly response = computed(() => this.assistant()?.response ?? null);

  /** Number of sources the model was shown - bounds which [S#] tags are valid. */
  protected readonly sourceCount = computed(() => {
    const response = this.response();
    if (!response) {
      return 0;
    }
    return response.debug?.retrieved.length ?? Math.max(0, ...response.sources.map((source) => source.rank));
  });

  protected readonly busy = this.store.isBusy;

  protected onAnswerClick(event: Event): void {
    const target = (event.target as HTMLElement | null)?.closest<HTMLElement>('[data-cite]');
    if (!target) {
      return;
    }
    const rank = Number(target.dataset['cite']);
    this.highlightedSource.update((current) => (current === rank ? null : rank));
  }

  protected copy(): void {
    const answer = this.response()?.answer;
    if (!answer) {
      return;
    }
    const sources = this.response()?.sources ?? [];
    const text =
      this.markdown.toPlainText(answer) +
      (sources.length ? '\n\nSources:\n' + sources.map((s) => `- ${s.source} › ${s.heading} (${s.page})`).join('\n') : '');
    navigator.clipboard
      ?.writeText(text)
      .then(() => this.notifications.success('Answer copied'))
      .catch(() => this.notifications.error('Could not copy to the clipboard'));
  }

  protected retry(): void {
    const assistant = this.assistant();
    if (assistant) {
      void this.store.retry(assistant.id);
    }
  }

  protected regenerate(): void {
    const assistant = this.assistant();
    if (assistant) {
      void this.store.regenerate(assistant.id);
    }
  }
}
