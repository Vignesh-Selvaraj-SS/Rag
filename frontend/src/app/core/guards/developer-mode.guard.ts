import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';
import { PreferencesStore } from '../services/preferences-store.service';

/** Developer tools are only reachable once Developer mode is switched on in Settings. */
export const developerModeGuard: CanActivateFn = () => {
  const preferences = inject(PreferencesStore);
  const router = inject(Router);

  return preferences.developerMode() ? true : router.createUrlTree(['/settings'], { queryParams: { developer: 'required' } });
};
