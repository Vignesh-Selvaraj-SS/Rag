import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import { API_PREFIX } from '../config/api.config';
import {
  SquadRaceStartRequest,
  SquadRaceStatusResponse,
  SquadRunRequest,
  SquadRunResponse,
} from '../models';

@Injectable({ providedIn: 'root' })
export class SquadApiService {
  private readonly http = inject(HttpClient);
  private readonly base = `${API_PREFIX}/squad`;

  run(request: SquadRunRequest): Observable<SquadRunResponse> {
    return this.http.post<SquadRunResponse>(`${this.base}/run`, request);
  }

  startRace(request: SquadRaceStartRequest): Observable<SquadRaceStatusResponse> {
    return this.http.post<SquadRaceStatusResponse>(`${this.base}/race/start`, request);
  }

  raceStatus(): Observable<SquadRaceStatusResponse> {
    return this.http.get<SquadRaceStatusResponse>(`${this.base}/race/status`);
  }
}
