import { TestBed } from '@angular/core/testing';
import { PreferencesStore } from './preferences-store.service';

describe('PreferencesStore', () => {
  beforeEach(() => {
    localStorage.clear();
    document.documentElement.removeAttribute('data-theme');
    TestBed.configureTestingModule({});
  });

  it('starts with server-neutral defaults', () => {
    const store = TestBed.inject(PreferencesStore);
    expect(store.mode()).toBe('dense');
    expect(store.topK()).toBeNull();
    expect(store.developerMode()).toBe(false);
    expect(store.hasRetrievalOverrides()).toBe(false);
  });

  it('persists updates to localStorage and restores them', async () => {
    const store = TestBed.inject(PreferencesStore);
    store.update({ mode: 'hybrid', topK: 8, developerMode: true });
    TestBed.tick();

    const raw = JSON.parse(localStorage.getItem('rag-assistant.preferences') ?? '{}');
    expect(raw.mode).toBe('hybrid');
    expect(raw.topK).toBe(8);
    expect(store.hasRetrievalOverrides()).toBe(true);

    TestBed.resetTestingModule();
    TestBed.configureTestingModule({});
    const restored = TestBed.inject(PreferencesStore);
    expect(restored.mode()).toBe('hybrid');
    expect(restored.developerMode()).toBe(true);
  });

  it('resets only retrieval settings', () => {
    const store = TestBed.inject(PreferencesStore);
    store.update({ mode: 'mmr', minScore: 0.5, source: 'a.md', developerMode: true });
    store.resetRetrieval();
    expect(store.mode()).toBe('dense');
    expect(store.minScore()).toBeNull();
    expect(store.source()).toBeNull();
    expect(store.developerMode()).toBe(true);
  });

  it('applies the theme to the document root', () => {
    const store = TestBed.inject(PreferencesStore);
    store.update({ theme: 'dark' });
    TestBed.tick();
    expect(document.documentElement.getAttribute('data-theme')).toBe('dark');
    store.update({ theme: 'system' });
    TestBed.tick();
    expect(document.documentElement.hasAttribute('data-theme')).toBe(false);
  });

  it('ignores corrupt storage', () => {
    localStorage.setItem('rag-assistant.preferences', '{not json');
    const store = TestBed.inject(PreferencesStore);
    expect(store.mode()).toBe('dense');
  });
});
