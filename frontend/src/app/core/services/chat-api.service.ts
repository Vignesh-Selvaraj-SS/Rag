import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import { API_PREFIX } from '../config/api.config';
import { ChatRequest, ChatResponse, SearchRequest, SearchResponse } from '../models';

@Injectable({ providedIn: 'root' })
export class ChatApiService {
  private readonly http = inject(HttpClient);

  ask(request: ChatRequest): Observable<ChatResponse> {
    return this.http.post<ChatResponse>(`${API_PREFIX}/chat`, request);
  }

  search(request: SearchRequest): Observable<SearchResponse> {
    return this.http.post<SearchResponse>(`${API_PREFIX}/search`, request);
  }
}
