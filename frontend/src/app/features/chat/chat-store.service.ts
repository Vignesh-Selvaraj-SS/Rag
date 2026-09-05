import { Injectable, computed, inject, signal } from '@angular/core';
import { firstValueFrom } from 'rxjs';
import { ApiError, ChatRequest, ChatResponse, RetrievalMode } from '../../core/models';
import { ChatApiService } from '../../core/services/chat-api.service';
import { PreferencesStore } from '../../core/services/preferences-store.service';

export interface UserMessage {
  id: string;
  role: 'user';
  text: string;
  createdAt: string;
}

export interface AssistantMessage {
  id: string;
  role: 'assistant';
  /** The question this answer responds to, so it can be retried/regenerated. */
  questionId: string;
  question: string;
  status: 'pending' | 'done' | 'error';
  response: ChatResponse | null;
  error: ApiError | null;
  createdAt: string;
  mode: RetrievalMode;
}

export type ChatMessage = UserMessage | AssistantMessage;

const STORAGE_KEY = 'rag-assistant.conversation';
const MAX_STORED_MESSAGES = 200;

/**
 * Conversation state for the Chat page. Each question is independent on the
 * server (the model gets no history), so the conversation is purely a client
 * record - kept in sessionStorage so a reload does not lose it.
 */
@Injectable({ providedIn: 'root' })
export class ChatStore {
  private readonly api = inject(ChatApiService);
  private readonly preferences = inject(PreferencesStore);

  private readonly state = signal<ChatMessage[]>(restore());
  private readonly busy = signal(false);

  readonly messages = this.state.asReadonly();
  readonly isBusy = this.busy.asReadonly();
  readonly isEmpty = computed(() => this.state().length === 0);
  readonly lastAssistant = computed(() => {
    const messages = this.state();
    for (let index = messages.length - 1; index >= 0; index -= 1) {
      const message = messages[index];
      if (message.role === 'assistant') {
        return message;
      }
    }
    return null;
  });

  async ask(question: string): Promise<void> {
    const text = question.trim();
    if (!text || this.busy()) {
      return;
    }

    const user: UserMessage = { id: newId(), role: 'user', text, createdAt: now() };
    const assistant = this.newAssistant(user.id, text);

    this.state.update((messages) => [...messages, user, assistant]);
    await this.run(assistant.id, text);
  }

  /** Re-send the same question into a NEW assistant message (keeps the failed/old one). */
  async regenerate(assistantId: string): Promise<void> {
    const original = this.find(assistantId);
    if (!original || this.busy()) {
      return;
    }
    const assistant = this.newAssistant(original.questionId, original.question);
    this.state.update((messages) => [...messages, assistant]);
    await this.run(assistant.id, original.question);
  }

  /** Retry a failed answer in place. */
  async retry(assistantId: string): Promise<void> {
    const original = this.find(assistantId);
    if (!original || this.busy()) {
      return;
    }
    this.patch(assistantId, { status: 'pending', error: null, response: null, mode: this.preferences.mode() });
    await this.run(assistantId, original.question);
  }

  clear(): void {
    this.state.set([]);
    persist([]);
  }

  private async run(assistantId: string, question: string): Promise<void> {
    this.busy.set(true);

    const request: ChatRequest = {
      question,
      mode: this.preferences.mode(),
      top_k: this.preferences.topK(),
      min_score: this.preferences.minScore(),
      source: this.preferences.source() || null,
      include_debug: this.preferences.developerMode(),
    };

    try {
      const response = await firstValueFrom(this.api.ask(request));
      this.patch(assistantId, { status: 'done', response, error: null });
    } catch (error) {
      this.patch(assistantId, { status: 'error', error: error as ApiError });
    } finally {
      this.busy.set(false);
      persist(this.state());
    }
  }

  private newAssistant(questionId: string, question: string): AssistantMessage {
    return {
      id: newId(),
      role: 'assistant',
      questionId,
      question,
      status: 'pending',
      response: null,
      error: null,
      createdAt: now(),
      mode: this.preferences.mode(),
    };
  }

  private find(assistantId: string): AssistantMessage | null {
    const message = this.state().find((entry) => entry.id === assistantId);
    return message && message.role === 'assistant' ? message : null;
  }

  private patch(assistantId: string, changes: Partial<AssistantMessage>): void {
    this.state.update((messages) =>
      messages.map((message) =>
        message.id === assistantId && message.role === 'assistant' ? { ...message, ...changes } : message,
      ),
    );
  }
}

function newId(): string {
  return globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function now(): string {
  return new Date().toISOString();
}

function restore(): ChatMessage[] {
  try {
    const raw = globalThis.sessionStorage?.getItem(STORAGE_KEY);
    if (!raw) {
      return [];
    }
    const parsed = JSON.parse(raw) as ChatMessage[];
    // A reload mid-request leaves a pending answer that will never resolve.
    return parsed.map((message) =>
      message.role === 'assistant' && message.status === 'pending'
        ? {
            ...message,
            status: 'error' as const,
            error: { message: 'The page was reloaded before the answer arrived.', status: 0, requestId: null, detail: null, url: null },
          }
        : message,
    );
  } catch {
    return [];
  }
}

function persist(messages: ChatMessage[]): void {
  try {
    globalThis.sessionStorage?.setItem(STORAGE_KEY, JSON.stringify(messages.slice(-MAX_STORED_MESSAGES)));
  } catch {
    // Storage full or unavailable: the conversation simply is not restored on reload.
  }
}
