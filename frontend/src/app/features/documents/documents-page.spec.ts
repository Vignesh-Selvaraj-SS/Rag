import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { errorInterceptor } from '../../core/interceptors/error.interceptor';
import { DocumentListResponse } from '../../core/models';
import { DocumentsPage } from './documents-page';

const SETTINGS = {
  app_name: 'RAG', version: '1', embedding_model: 'e', collection: 'c',
  defaults: { mode: 'dense', top_k: 5, min_score: 0.6 },
  generation: { model: 'm', temperature: 0, max_tokens: 800, prompt_version: 'v1', configured: true },
  constants: { candidate_pool_size: 25, rrf_k: 60, mmr_lambda: 0.5, reranker_model: 'r', fixed_chunk_words: 300, fixed_chunk_overlap_words: 50, hnsw_m: 16, hnsw_ef_construct: 100, hnsw_ef_search: 128 },
  modes: [{ id: 'dense', label: 'Meaning', description: '', requires_llm: false }],
  strategies: [{ id: 'heading', label: 'By heading', description: 'sections' }, { id: 'fixed_size', label: 'Fixed size', description: 'windows' }],
  traces_enabled: true, max_upload_mb: 20, supported_extensions: ['.md', '.pdf', '.txt'],
};

const LIST: DocumentListResponse = {
  documents: [
    { name: 'policy.md', extension: 'md', bytes: 6723, modified_at: '2026-09-01T10:00:00Z', status: 'indexed', pages: 1, words: 900, chunks: 12 },
    { name: 'new.pdf', extension: 'pdf', bytes: 10152, modified_at: '2026-09-04T10:00:00Z', status: 'pending', pages: null, words: null, chunks: null },
  ],
  index: { chunks: 122, ready: true, strategy: 'heading', built_at: '2026-09-03T10:00:00Z', documents: 1, words: 900, collection: 'c', embedding_model: 'e' },
};

describe('DocumentsPage', () => {
  let http: HttpTestingController;

  beforeEach(() => {
    localStorage.clear();
    TestBed.configureTestingModule({
      imports: [DocumentsPage],
      providers: [provideRouter([]), provideHttpClient(withInterceptors([errorInterceptor])), provideHttpClientTesting()],
    });
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => http.verify());

  function create() {
    const fixture = TestBed.createComponent(DocumentsPage);
    fixture.detectChanges();
    http.expectOne('/api/v1/settings').flush(SETTINGS);
    return fixture;
  }

  it('lists documents with their status and the knowledge base summary', async () => {
    const fixture = create();
    http.expectOne('/api/v1/documents').flush(LIST);
    await fixture.whenStable();

    const text = (fixture.nativeElement as HTMLElement).textContent ?? '';
    expect(text).toContain('policy.md');
    expect(text).toContain('Indexed');
    expect(text).toContain('Needs rebuild');
    expect(text).toContain('122');
    expect(text).toContain('1 change pending');
  });

  it('shows an empty state when there are no documents', async () => {
    const fixture = create();
    http.expectOne('/api/v1/documents').flush({ documents: [], index: { ...LIST.index, chunks: 0, ready: false, strategy: null, built_at: null, documents: null, words: null } });
    await fixture.whenStable();

    const text = (fixture.nativeElement as HTMLElement).textContent ?? '';
    expect(text).toContain('No documents yet');
  });

  it('shows an error state with retry when loading fails', async () => {
    const fixture = create();
    http.expectOne('/api/v1/documents').flush({ detail: 'nope' }, { status: 500, statusText: 'Server Error' });
    await fixture.whenStable();

    const element = fixture.nativeElement as HTMLElement;
    expect(element.textContent).toContain('Unable to load documents');

    element.querySelector<HTMLButtonElement>('app-error-state button')!.click();
    http.expectOne('/api/v1/documents').flush(LIST);
    await fixture.whenStable();
    expect(element.textContent).toContain('policy.md');
  });

  it('rebuilds the index with the chosen strategy', async () => {
    const fixture = create();
    http.expectOne('/api/v1/documents').flush(LIST);
    await fixture.whenStable();

    const component = fixture.componentInstance as unknown as { strategy: { set(value: string): void }; rebuild(): Promise<void> };
    component.strategy.set('fixed_size');
    const rebuilding = component.rebuild();

    const request = http.expectOne('/api/v1/index/rebuild');
    expect(request.request.body).toEqual({ strategy: 'fixed_size' });
    request.flush({ strategy: 'fixed_size', documents: 2, words: 1000, chunks: 40, built_at: '2026-09-04T11:00:00Z', per_document: [] });
    // The reload is issued after the rebuild promise resolves (next microtask).
    await new Promise((resolve) => setTimeout(resolve, 0));
    http.expectOne('/api/v1/documents').flush(LIST);
    await rebuilding;
  });
});
