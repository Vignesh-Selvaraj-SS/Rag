import { TestBed } from '@angular/core/testing';
import { ActivatedRouteSnapshot, Router, RouterStateSnapshot, UrlTree } from '@angular/router';
import { PreferencesStore } from '../services/preferences-store.service';
import { developerModeGuard } from './developer-mode.guard';

describe('developerModeGuard', () => {
  beforeEach(() => {
    localStorage.clear();
    TestBed.configureTestingModule({});
  });

  const run = () =>
    TestBed.runInInjectionContext(() => developerModeGuard({} as ActivatedRouteSnapshot, {} as RouterStateSnapshot));

  it('redirects to settings when developer mode is off', () => {
    const result = run() as UrlTree;
    expect(result instanceof UrlTree).toBe(true);
    expect(TestBed.inject(Router).serializeUrl(result)).toBe('/settings?developer=required');
  });

  it('allows navigation when developer mode is on', () => {
    TestBed.inject(PreferencesStore).setDeveloperMode(true);
    expect(run()).toBe(true);
  });
});
