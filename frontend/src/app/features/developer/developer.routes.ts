import { Routes } from '@angular/router';

export const DEVELOPER_ROUTES: Routes = [
  {
    path: '',
    loadComponent: () => import('./developer-shell/developer-shell').then((m) => m.DeveloperShell),
    children: [
      { path: '', pathMatch: 'full', redirectTo: 'retrieval' },
      {
        path: 'retrieval',
        title: 'Retrieval inspector · RAG Assistant',
        loadComponent: () => import('./retrieval-inspector/retrieval-inspector').then((m) => m.RetrievalInspector),
      },
      {
        path: 'traces',
        title: 'Traces · RAG Assistant',
        loadComponent: () => import('./traces/traces-page').then((m) => m.TracesPage),
      },
      {
        path: 'traces/:traceId',
        title: 'Trace · RAG Assistant',
        loadComponent: () => import('./traces/trace-detail').then((m) => m.TraceDetailPage),
      },
    ],
  },
];
