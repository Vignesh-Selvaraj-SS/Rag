import { HttpInterceptorFn } from '@angular/common/http';
import { inject } from '@angular/core';
import { API_BASE_URL } from '../config/api.config';

/** Prefix relative `/api/...` and `/health` calls with the configured API host. */
export const apiBaseUrlInterceptor: HttpInterceptorFn = (request, next) => {
  const baseUrl = inject(API_BASE_URL);

  if (!baseUrl || /^https?:\/\//i.test(request.url) || !request.url.startsWith('/')) {
    return next(request);
  }

  return next(request.clone({ url: `${baseUrl}${request.url}` }));
};
