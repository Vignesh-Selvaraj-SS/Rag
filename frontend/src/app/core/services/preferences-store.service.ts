import { Injectable, computed, effect, signal } from '@angular/core';
import { RetrievalMode, UserPreferences } from '../models';

const STORAGE_KEY = 'rag-assistant.preferences';

const DEFAULTS: UserPreferences = {
  mode: 'dense',
  topK: null,
  minScore: null,
  source: null,
  developerMode: false,
  theme: 'system',
};

/**
 * User preferences that live in the browser: retrieval defaults sent with
 * every question, Developer mode, and theme. Persisted to localStorage; the
 * server holds no per-user state.
 */
@Injectable({ providedIn: 'root' })
export class PreferencesStore {
  private readonly state = signal<UserPreferences>(load());

  readonly preferences = this.state.asReadonly();
  readonly mode = computed(() => this.state().mode);
  readonly topK = computed(() => this.state().topK);
  readonly minScore = computed(() => this.state().minScore);
  readonly source = computed(() => this.state().source);
  readonly developerMode = computed(() => this.state().developerMode);
  readonly theme = computed(() => this.state().theme);

  /** True when any retrieval default differs from the server defaults. */
  readonly hasRetrievalOverrides = computed(
    () => this.state().topK !== null || this.state().minScore !== null || !!this.state().source,
  );

  constructor() {
    effect(() => persist(this.state()));
    effect(() => applyTheme(this.state().theme));
  }

  update(patch: Partial<UserPreferences>): void {
    this.state.update((current) => ({ ...current, ...patch }));
  }

  setMode(mode: RetrievalMode): void {
    this.update({ mode });
  }

  setDeveloperMode(enabled: boolean): void {
    this.update({ developerMode: enabled });
  }

  resetRetrieval(): void {
    this.update({ mode: DEFAULTS.mode, topK: null, minScore: null, source: null });
  }
}

function load(): UserPreferences {
  try {
    const raw = globalThis.localStorage?.getItem(STORAGE_KEY);
    if (!raw) {
      return { ...DEFAULTS };
    }
    const parsed = JSON.parse(raw) as Partial<UserPreferences>;
    return { ...DEFAULTS, ...parsed };
  } catch {
    return { ...DEFAULTS };
  }
}

function persist(preferences: UserPreferences): void {
  try {
    globalThis.localStorage?.setItem(STORAGE_KEY, JSON.stringify(preferences));
  } catch {
    // Storage may be unavailable (private mode); preferences then last for the session only.
  }
}

function applyTheme(theme: UserPreferences['theme']): void {
  const root = globalThis.document?.documentElement;
  if (!root) {
    return;
  }
  if (theme === 'system') {
    root.removeAttribute('data-theme');
  } else {
    root.setAttribute('data-theme', theme);
  }
}
