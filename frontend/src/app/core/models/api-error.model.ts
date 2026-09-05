/**
 * Every failed request is normalised to this shape by the error interceptor,
 * so components can show `message` and Developer mode can show the rest.
 */
export interface ApiError {
  /** User-friendly message, safe to display. */
  message: string;
  /** HTTP status, 0 when the server could not be reached. */
  status: number;
  /** Server-side request id, when the backend answered. */
  requestId: string | null;
  /** Raw backend detail (technical), for Developer mode. */
  detail: string | null;
  url: string | null;
}

export function isApiError(value: unknown): value is ApiError {
  return (
    typeof value === 'object' &&
    value !== null &&
    'message' in value &&
    'status' in value &&
    'requestId' in value
  );
}
