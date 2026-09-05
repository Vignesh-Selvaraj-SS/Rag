import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable, shareReplay } from 'rxjs';
import { API_PREFIX } from '../config/api.config';
import { AppSettings, HealthResponse } from '../models';

@Injectable({ providedIn: 'root' })
export class SettingsApiService {
  private readonly http = inject(HttpClient);
  private cached$: Observable<AppSettings> | null = null;

  /** Server configuration and catalogs. Static for the life of the server, so fetched once. */
  settings(force = false): Observable<AppSettings> {
    if (!this.cached$ || force) {
      this.cached$ = this.http.get<AppSettings>(`${API_PREFIX}/settings`).pipe(shareReplay(1));
    }
    return this.cached$;
  }

  health(): Observable<HealthResponse> {
    return this.http.get<HealthResponse>('/health');
  }
}
