import { HttpErrorResponse, HttpInterceptorFn } from '@angular/common/http';
import { catchError, throwError } from 'rxjs';
import { ApiError } from '../models/api-error.model';

const FRIENDLY_BY_STATUS: Record<number, string> = {
  0: 'Could not reach the server. Check that the API is running.',
  400: 'The request could not be processed.',
  404: 'The requested item was not found.',
  413: 'The file is too large.',
  422: 'Some of the values entered are not valid.',
  500: 'Something went wrong on the server.',
  502: 'The language model service is not responding. Please try again.',
  503: 'The service is not ready yet.',
  504: 'The server took too long to respond.',
};

/**
 * Turn every HttpErrorResponse into an ApiError. The backend already returns
 * plain-English `detail` messages for expected failures (empty index, bad
 * upload, missing key), so those are shown as-is; anything else gets a
 * generic message by status.
 */
export const errorInterceptor: HttpInterceptorFn = (request, next) =>
  next(request).pipe(
    catchError((error: unknown) => throwError(() => toApiError(error, request.url))),
  );

export function toApiError(error: unknown, url: string | null = null): ApiError {
  if (error instanceof HttpErrorResponse) {
    const body = error.error as { detail?: unknown; request_id?: unknown } | null;
    const detail = typeof body?.detail === 'string' ? body.detail : null;
    const requestId = typeof body?.request_id === 'string' ? body.request_id : null;
    const generic = FRIENDLY_BY_STATUS[error.status] ?? 'Something went wrong.';

    return {
      message: detail && error.status < 500 ? detail : detail && error.status === 503 ? detail : generic,
      status: error.status,
      requestId,
      detail: detail ?? (error.status === 0 ? error.message : null),
      url: error.url ?? url,
    };
  }

  return {
    message: 'Something went wrong.',
    status: 0,
    requestId: null,
    detail: error instanceof Error ? error.message : String(error),
    url,
  };
}
