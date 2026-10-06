import { Routes } from '@angular/router';
import { developerModeGuard } from './core/guards/developer-mode.guard';

export const routes: Routes = [
  {
    path: '',
    loadComponent: () => import('./layout/main-layout/main-layout').then((m) => m.MainLayout),
    children: [
      { path: '', pathMatch: 'full', redirectTo: 'chat' },
      {
        path: 'chat',
        title: 'Chat · RAG Assistant',
        loadComponent: () => import('./features/chat/chat-page').then((m) => m.ChatPage),
      },
      {
        path: 'documents',
        title: 'Documents · RAG Assistant',
        loadComponent: () => import('./features/documents/documents-page').then((m) => m.DocumentsPage),
      },
      {
        path: 'evaluation',
        title: 'Evaluation · RAG Assistant',
        loadComponent: () => import('./features/evaluation/evaluation-page').then((m) => m.EvaluationPage),
      },
      {
        path: 'analytics',
        title: 'Analytics · RAG Assistant',
        loadComponent: () => import('./features/analytics/analytics-page').then((m) => m.AnalyticsPage),
      },
      {
        path: 'agent',
        title: 'Agent · RAG Assistant',
        loadComponent: () => import('./features/agent/agent-page').then((m) => m.AgentPage),
      },
      {
        path: 'squad',
        title: 'Claims Squad · RAG Assistant',
        loadComponent: () => import('./features/squad/squad-page').then((m) => m.SquadPage),
      },
      {
        path: 'squad-race',
        title: 'Squad Race · RAG Assistant',
        loadComponent: () => import('./features/squad-race/squad-race-page').then((m) => m.SquadRacePage),
      },
      {
        path: 'settings',
        title: 'Settings · RAG Assistant',
        loadComponent: () => import('./features/settings/settings-page').then((m) => m.SettingsPage),
      },
      {
        path: 'developer',
        canActivate: [developerModeGuard],
        loadChildren: () => import('./features/developer/developer.routes').then((m) => m.DEVELOPER_ROUTES),
      },
      { path: '**', redirectTo: 'chat' },
    ],
  },
];
