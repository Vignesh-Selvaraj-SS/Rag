import { ChangeDetectionStrategy, Component } from '@angular/core';
import { RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { PageHeader } from '../../../shared/components/page-header/page-header';

@Component({
  selector: 'app-developer-shell',
  imports: [RouterOutlet, RouterLink, RouterLinkActive, PageHeader],
  template: `
    <div class="page">
      <app-page-header title="Developer tools" subtitle="See what the pipeline actually did: retrieval scores, recorded traces, quality checks and replays." />
      <nav class="tabs" aria-label="Developer sections">
        <a class="tab" routerLink="retrieval" routerLinkActive="active" ariaCurrentWhenActive="page">Retrieval inspector</a>
        <a class="tab" routerLink="traces" routerLinkActive="active" ariaCurrentWhenActive="page">Traces</a>
      </nav>
      <router-outlet />
    </div>
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class DeveloperShell {}
