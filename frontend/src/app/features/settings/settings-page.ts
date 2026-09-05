import { ChangeDetectionStrategy, Component, computed, effect, inject, input } from '@angular/core';
import { TitleCasePipe } from '@angular/common';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { RetrievalMode, UserPreferences } from '../../core/models';
import { NotificationService } from '../../core/services/notification.service';
import { PreferencesStore } from '../../core/services/preferences-store.service';
import { ServerConfigService } from '../../core/services/server-config.service';
import { ErrorState } from '../../shared/components/error-state/error-state';
import { PageHeader } from '../../shared/components/page-header/page-header';

@Component({
  selector: 'app-settings-page',
  imports: [ReactiveFormsModule, RouterLink, TitleCasePipe, ErrorState, PageHeader],
  templateUrl: './settings-page.html',
  styleUrl: './settings-page.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class SettingsPage {
  /** Set by the developer guard when someone opens /developer with the mode off. */
  readonly developer = input<string>();

  private readonly formBuilder = inject(FormBuilder).nonNullable;
  private readonly notifications = inject(NotificationService);
  protected readonly preferences = inject(PreferencesStore);
  protected readonly serverConfig = inject(ServerConfigService);

  protected readonly form = this.formBuilder.group({
    mode: this.formBuilder.control<RetrievalMode>('dense'),
    topK: this.formBuilder.control<number | null>(null, [Validators.min(1), Validators.max(50)]),
    minScore: this.formBuilder.control<number | null>(null, [Validators.min(0), Validators.max(1)]),
    source: this.formBuilder.control<string>('', [Validators.maxLength(255)]),
  });

  protected readonly selectedMode = computed(() => this.serverConfig.modes().find((m) => m.id === this.form.controls.mode.value));
  protected readonly redirectedFromDeveloper = computed(() => this.developer() === 'required');

  constructor() {
    this.serverConfig.load();
    effect(() => {
      const current = this.preferences.preferences();
      this.form.reset(
        { mode: current.mode, topK: current.topK, minScore: current.minScore, source: current.source ?? '' },
        { emitEvent: false },
      );
    });
  }

  protected save(): void {
    if (this.form.invalid) {
      this.form.markAllAsTouched();
      return;
    }
    const value = this.form.getRawValue();
    const patch: Partial<UserPreferences> = {
      mode: value.mode,
      topK: value.topK === null || value.topK === ('' as unknown) ? null : Number(value.topK),
      minScore: value.minScore === null || value.minScore === ('' as unknown) ? null : Number(value.minScore),
      source: value.source.trim() || null,
    };
    this.preferences.update(patch);
    this.notifications.success('Retrieval settings saved');
  }

  protected reset(): void {
    this.preferences.resetRetrieval();
    this.notifications.info('Retrieval settings reset to the server defaults');
  }

  protected toggleDeveloper(): void {
    this.preferences.setDeveloperMode(!this.preferences.developerMode());
  }

  protected setTheme(theme: UserPreferences['theme']): void {
    this.preferences.update({ theme });
  }
}
