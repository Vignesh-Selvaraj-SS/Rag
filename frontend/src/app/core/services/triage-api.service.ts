import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import { API_PREFIX } from '../config/api.config';
import { TriageClaimSummary, TriageRunRequest, TriageRunResponse } from '../models';

@Injectable({ providedIn: 'root' })
export class TriageApiService {
  private readonly http = inject(HttpClient);
  private readonly base = `${API_PREFIX}/triage`;

  claims(): Observable<TriageClaimSummary[]> {
    return this.http.get<TriageClaimSummary[]>(`${this.base}/claims`);
  }

  run(request: TriageRunRequest): Observable<TriageRunResponse> {
    return this.http.post<TriageRunResponse>(`${this.base}/run`, request);
  }
}
