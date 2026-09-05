import { HttpClient, HttpEvent } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import { API_PREFIX } from '../config/api.config';
import {
  ChunkStrategy,
  DeleteResponse,
  DocumentListResponse,
  IndexStatus,
  RebuildResponse,
  UploadResponse,
} from '../models';

@Injectable({ providedIn: 'root' })
export class DocumentApiService {
  private readonly http = inject(HttpClient);

  list(): Observable<DocumentListResponse> {
    return this.http.get<DocumentListResponse>(`${API_PREFIX}/documents`);
  }

  upload(file: File): Observable<HttpEvent<UploadResponse>> {
    const body = new FormData();
    body.append('file', file, file.name);
    return this.http.post<UploadResponse>(`${API_PREFIX}/documents`, body, {
      reportProgress: true,
      observe: 'events',
    });
  }

  delete(name: string): Observable<DeleteResponse> {
    return this.http.delete<DeleteResponse>(`${API_PREFIX}/documents/${encodeURIComponent(name)}`);
  }

  indexStatus(): Observable<IndexStatus> {
    return this.http.get<IndexStatus>(`${API_PREFIX}/index`);
  }

  rebuild(strategy: ChunkStrategy): Observable<RebuildResponse> {
    return this.http.post<RebuildResponse>(`${API_PREFIX}/index/rebuild`, { strategy });
  }
}
