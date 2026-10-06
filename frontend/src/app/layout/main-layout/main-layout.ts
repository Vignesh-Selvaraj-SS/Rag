import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { PreferencesStore } from '../../core/services/preferences-store.service';
import { ServerConfigService } from '../../core/services/server-config.service';
import { HealthIndicator } from '../health-indicator/health-indicator';

interface NavItem {
  path: string;
  label: string;
  icon: string;
  developer?: boolean;
}

const NAV: NavItem[] = [
  { path: '/chat', label: 'Chat', icon: '💬' },
  { path: '/documents', label: 'Documents', icon: '📄' },
  { path: '/evaluation', label: 'Evaluation', icon: '🎯' },
  { path: '/analytics', label: 'Analytics', icon: '📈' },
  { path: '/agent', label: 'Agent', icon: '🧭' },
  { path: '/squad', label: 'Claims Squad', icon: '🧑‍🤝‍🧑' },
  { path: '/squad-race', label: 'Squad Race', icon: '🏁' },
  { path: '/settings', label: 'Settings', icon: '⚙️' },
  { path: '/developer', label: 'Developer', icon: '🛠️', developer: true },
];

@Component({
  selector: 'app-main-layout',
  imports: [RouterOutlet, RouterLink, RouterLinkActive, HealthIndicator],
  templateUrl: './main-layout.html',
  styleUrl: './main-layout.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class MainLayout {
  private readonly preferences = inject(PreferencesStore);
  private readonly serverConfig = inject(ServerConfigService);

  protected readonly menuOpen = signal(false);
  protected readonly appName = computed(() => this.serverConfig.settings()?.app_name ?? 'RAG Assistant');
  protected readonly version = computed(() => this.serverConfig.settings()?.version ?? '');
  protected readonly items = computed(() =>
    NAV.filter((item) => !item.developer || this.preferences.developerMode()),
  );

  constructor() {
    this.serverConfig.load();
  }

  protected toggleMenu(): void {
    this.menuOpen.update((open) => !open);
  }

  protected closeMenu(): void {
    this.menuOpen.set(false);
  }
}
