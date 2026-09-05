import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { TestBed } from '@angular/core/testing';
import { errorInterceptor } from '../../core/interceptors/error.interceptor';
import { ChatResponse } from '../../core/models';
import { PreferencesStore } from '../../core/services/preferences-store.service';
import { ChatStore } from './chat-store.service';

const RESPONSE: ChatResponse = {
  answer: 'A $500 deductible applies [S1].',
  sources: [{ rank: 1, chunk_id: 'a.md::4', source: 'a.md', heading: 'Deductible', page: 'p.1' }],
  refused: false,
  refused_by: null,
  mode: 'dense',
  latency_ms: 1200,
  trace_id: 't_abc',
  debug: null,
};

describe('ChatStore', () => {
  let store: ChatStore;
  let http: HttpTestingController;

  beforeEach(() => {
    localStorage.clear();
    sessionStorage.clear();
    TestBed.configureTestingModule({
      providers: [provideHttpClient(withInterceptors([errorInterceptor])), provideHttpClientTesting()],
    });
    store = TestBed.inject(ChatStore);
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => http.verify());

  it('adds a user message and a pending assistant message, then fills in the answer', async () => {
    const asking = store.ask('What deductible applies?');

    expect(store.messages().length).toBe(2);
    expect(store.messages()[1]).toMatchObject({ role: 'assistant', status: 'pending' });
    expect(store.isBusy()).toBe(true);

    const request = http.expectOne('/api/v1/chat');
    expect(request.request.body).toMatchObject({
      question: 'What deductible applies?',
      mode: 'dense',
      top_k: null,
      include_debug: false,
    });
    request.flush(RESPONSE);
    await asking;

    const assistant = store.lastAssistant();
    expect(assistant?.status).toBe('done');
    expect(assistant?.response?.answer).toContain('$500');
    expect(store.isBusy()).toBe(false);
  });

  it('sends the retrieval preferences and debug flag with the request', async () => {
    const preferences = TestBed.inject(PreferencesStore);
    preferences.update({ mode: 'hybrid', topK: 3, minScore: 0.5, source: 'a.md', developerMode: true });

    const asking = store.ask('q');
    const request = http.expectOne('/api/v1/chat');
    expect(request.request.body).toEqual({
      question: 'q',
      mode: 'hybrid',
      top_k: 3,
      min_score: 0.5,
      source: 'a.md',
      include_debug: true,
    });
    request.flush(RESPONSE);
    await asking;
  });

  it('records a friendly error and allows retry in place', async () => {
    const asking = store.ask('q');
    http.expectOne('/api/v1/chat').flush({ detail: 'The knowledge base has not been indexed yet.', request_id: 'r1' }, { status: 503, statusText: 'Service Unavailable' });
    await asking;

    const failed = store.lastAssistant();
    expect(failed?.status).toBe('error');
    expect(failed?.error?.message).toBe('The knowledge base has not been indexed yet.');
    expect(failed?.error?.requestId).toBe('r1');

    const retrying = store.retry(failed!.id);
    expect(store.lastAssistant()?.status).toBe('pending');
    http.expectOne('/api/v1/chat').flush(RESPONSE);
    await retrying;

    expect(store.messages().length).toBe(2);
    expect(store.lastAssistant()?.status).toBe('done');
  });

  it('regenerate appends a new answer for the same question', async () => {
    const asking = store.ask('q');
    http.expectOne('/api/v1/chat').flush(RESPONSE);
    await asking;

    const regenerating = store.regenerate(store.lastAssistant()!.id);
    expect(store.messages().length).toBe(3);
    http.expectOne('/api/v1/chat').flush({ ...RESPONSE, answer: 'Second answer [S1].' });
    await regenerating;

    expect(store.lastAssistant()?.response?.answer).toBe('Second answer [S1].');
  });

  it('ignores blank questions and clears the conversation', async () => {
    await store.ask('   ');
    expect(store.isEmpty()).toBe(true);

    const asking = store.ask('q');
    http.expectOne('/api/v1/chat').flush(RESPONSE);
    await asking;
    expect(sessionStorage.getItem('rag-assistant.conversation')).toContain('$500');

    store.clear();
    expect(store.isEmpty()).toBe(true);
    expect(sessionStorage.getItem('rag-assistant.conversation')).toBe('[]');
  });
});
