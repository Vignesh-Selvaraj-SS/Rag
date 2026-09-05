import {
  AfterViewChecked,
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  computed,
  inject,
  signal,
  viewChild,
} from '@angular/core';
import { RouterLink } from '@angular/router';
import { PreferencesStore } from '../../core/services/preferences-store.service';
import { ServerConfigService } from '../../core/services/server-config.service';
import { EmptyState } from '../../shared/components/empty-state/empty-state';
import { ChatComposer } from './components/chat-composer/chat-composer';
import { ChatMessageItem } from './components/chat-message/chat-message';
import { ChatStore } from './chat-store.service';

export const SAMPLE_QUESTIONS = [
  'What deductible applies to a water backup claim?',
  'Is a dented metal roof covered?',
  'Someone opened a credit card in my name, what’s covered?',
  'My air conditioner broke down suddenly, is that a claim?',
  'How much jewellery is covered without an appraisal?',
  'How quickly will someone contact me after I report a claim?',
];

@Component({
  selector: 'app-chat-page',
  imports: [RouterLink, EmptyState, ChatComposer, ChatMessageItem],
  templateUrl: './chat-page.html',
  styleUrl: './chat-page.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ChatPage implements AfterViewChecked {
  protected readonly store = inject(ChatStore);
  protected readonly preferences = inject(PreferencesStore);
  protected readonly serverConfig = inject(ServerConfigService);

  protected readonly samples = SAMPLE_QUESTIONS;
  protected readonly clearConfirm = signal(false);
  protected readonly modeLabel = computed(() => this.serverConfig.modeLabel(this.preferences.mode()));
  protected readonly llmMissing = computed(() => this.serverConfig.settings() !== null && !this.serverConfig.llmConfigured());

  private readonly feed = viewChild<ElementRef<HTMLElement>>('feed');
  private lastCount = 0;
  private lastBusy = false;

  constructor() {
    this.serverConfig.load();
  }

  ngAfterViewChecked(): void {
    const count = this.store.messages().length;
    const busy = this.store.isBusy();
    if (count !== this.lastCount || busy !== this.lastBusy) {
      this.lastCount = count;
      this.lastBusy = busy;
      this.scrollToBottom();
    }
  }

  protected send(question: string): void {
    void this.store.ask(question);
  }

  protected clear(): void {
    this.store.clear();
    this.clearConfirm.set(false);
  }

  private scrollToBottom(): void {
    const element = this.feed()?.nativeElement;
    if (element) {
      element.scrollTop = element.scrollHeight;
    }
  }
}
