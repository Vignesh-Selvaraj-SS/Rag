import { InjectionToken } from '@angular/core';
import { environment } from '../../../environments/environment';

/** Base URL for API calls. Empty means same origin (production build served by FastAPI). */
export const API_BASE_URL = new InjectionToken<string>('API_BASE_URL', {
  providedIn: 'root',
  factory: () => environment.apiBaseUrl,
});

export const API_PREFIX = '/api/v1';
