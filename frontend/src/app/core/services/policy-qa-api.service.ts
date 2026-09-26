import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import { API_PREFIX } from '../config/api.config';
import { PolicyQaRequest, PolicyQaResponse } from '../models';

@Injectable({ providedIn: 'root' })
export class PolicyQaApiService {
  private readonly http = inject(HttpClient);
  private readonly base = `${API_PREFIX}/policy-qa`;

  ask(request: PolicyQaRequest): Observable<PolicyQaResponse> {
    return this.http.post<PolicyQaResponse>(`${this.base}/ask`, request);
  }
}
