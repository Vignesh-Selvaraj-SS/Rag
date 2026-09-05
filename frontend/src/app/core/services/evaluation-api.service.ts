import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable, map } from 'rxjs';
import { API_PREFIX } from '../config/api.config';
import {
  EvaluationRun,
  EvaluationRunRequest,
  EvaluationRunSummary,
  GoldenQuestion,
  InspectResponse,
  RetrievalMode,
} from '../models';

@Injectable({ providedIn: 'root' })
export class EvaluationApiService {
  private readonly http = inject(HttpClient);
  private readonly base = `${API_PREFIX}/evaluation`;

  goldenSet(): Observable<GoldenQuestion[]> {
    return this.http.get<{ items: GoldenQuestion[] }>(`${this.base}/golden-set`).pipe(map((r) => r.items));
  }

  saveGoldenSet(items: GoldenQuestion[]): Observable<GoldenQuestion[]> {
    return this.http
      .put<{ items: GoldenQuestion[] }>(`${this.base}/golden-set`, { items })
      .pipe(map((r) => r.items));
  }

  run(request: EvaluationRunRequest): Observable<EvaluationRun> {
    return this.http.post<EvaluationRun>(`${this.base}/runs`, request);
  }

  runs(): Observable<EvaluationRunSummary[]> {
    return this.http.get<EvaluationRunSummary[]>(`${this.base}/runs`);
  }

  getRun(runId: string): Observable<EvaluationRun> {
    return this.http.get<EvaluationRun>(`${this.base}/runs/${encodeURIComponent(runId)}`);
  }

  deleteRun(runId: string): Observable<void> {
    return this.http.delete<void>(`${this.base}/runs/${encodeURIComponent(runId)}`);
  }

  inspect(questionId: string, mode: RetrievalMode): Observable<InspectResponse> {
    return this.http.post<InspectResponse>(`${this.base}/inspect`, { question_id: questionId, mode });
  }
}
