import { HttpErrorResponse } from '@angular/common/http';
import { toApiError } from './error.interceptor';

describe('toApiError', () => {
  it('uses the backend detail for client errors', () => {
    const error = toApiError(
      new HttpErrorResponse({ status: 400, url: '/api/v1/documents', error: { detail: 'Unsupported file type', request_id: 'abc' } }),
    );
    expect(error).toEqual({
      message: 'Unsupported file type',
      status: 400,
      requestId: 'abc',
      detail: 'Unsupported file type',
      url: '/api/v1/documents',
    });
  });

  it('keeps the backend detail for 503 (not configured / not indexed) but hides 500 details', () => {
    expect(toApiError(new HttpErrorResponse({ status: 503, error: { detail: 'Set GROQ_API_KEY.' } })).message).toBe('Set GROQ_API_KEY.');
    const server = toApiError(new HttpErrorResponse({ status: 500, error: { detail: 'Traceback…', request_id: 'r' } }));
    expect(server.message).toBe('Something went wrong on the server.');
    expect(server.detail).toBe('Traceback…');
    expect(server.requestId).toBe('r');
  });

  it('explains network failures', () => {
    const error = toApiError(new HttpErrorResponse({ status: 0, statusText: 'Unknown Error' }));
    expect(error.status).toBe(0);
    expect(error.message).toContain('Could not reach the server');
  });

  it('wraps non-HTTP errors', () => {
    const error = toApiError(new Error('boom'), '/x');
    expect(error.message).toBe('Something went wrong.');
    expect(error.detail).toBe('boom');
    expect(error.url).toBe('/x');
  });
});
