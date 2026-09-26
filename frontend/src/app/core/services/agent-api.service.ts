import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import { API_PREFIX } from '../config/api.config';
import { AgentClaimSummary, AgentRunRequest, AgentRunResponse } from '../models';

@Injectable({ providedIn: 'root' })
export class AgentApiService {
  private readonly http = inject(HttpClient);
  private readonly base = `${API_PREFIX}/agent`;

  claims(): Observable<AgentClaimSummary[]> {
    return this.http.get<AgentClaimSummary[]>(`${this.base}/claims`);
  }

  run(request: AgentRunRequest): Observable<AgentRunResponse> {
    return this.http.post<AgentRunResponse>(`${this.base}/run`, request);
  }
}
