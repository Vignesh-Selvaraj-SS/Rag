import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import { API_PREFIX } from '../config/api.config';
import { ReplayResponse, TraceDetail, TraceListQuery, TraceListResponse, TraceSampleResponse, TraceStats } from '../models';

@Injectable({ providedIn: 'root' })
export class TraceApiService {
  private readonly http = inject(HttpClient);
  private readonly base = `${API_PREFIX}/traces`;

  list(query: TraceListQuery = {}): Observable<TraceListResponse> {
    let params = new HttpParams()
      .set('limit', String(query.limit ?? 50))
      .set('offset', String(query.offset ?? 0));

    if (query.refused !== null && query.refused !== undefined) {
      params = params.set('refused', String(query.refused));
    }
    if (query.mode) {
      params = params.set('mode', query.mode);
    }
    if (query.search) {
      params = params.set('search', query.search);
    }

    return this.http.get<TraceListResponse>(this.base, { params });
  }

  get(traceId: string): Observable<TraceDetail> {
    return this.http.get<TraceDetail>(`${this.base}/${encodeURIComponent(traceId)}`);
  }

  stats(): Observable<TraceStats> {
    return this.http.get<TraceStats>(`${this.base}/stats`);
  }

  sample(seed: number, n: number): Observable<TraceSampleResponse> {
    const params = new HttpParams().set('seed', String(seed)).set('n', String(n));
    return this.http.get<TraceSampleResponse>(`${this.base}/sample`, { params });
  }

  replay(traceId: string): Observable<ReplayResponse> {
    return this.http.post<ReplayResponse>(`${this.base}/${encodeURIComponent(traceId)}/replay`, {});
  }
}
