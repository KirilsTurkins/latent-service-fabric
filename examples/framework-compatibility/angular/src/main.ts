import {Component, enableProdMode, provideZonelessChangeDetection} from '@angular/core';
import {APP_BASE_HREF} from '@angular/common';
import {bootstrapApplication} from '@angular/platform-browser';
import {provideRouter, RouterLink, RouterOutlet} from '@angular/router';
import {provideAnimationsAsync} from '@angular/platform-browser/animations/async';
import {providePrimeNG} from 'primeng/config';
import {ButtonModule} from 'primeng/button';
import Aura from '@primeuix/themes/aura';
import Lara from '@primeuix/themes/lara';
import {usePreset} from '@primeuix/themes';

declare const LSF_MOUNT: string;
@Component({selector: 'lsf-framework-app', standalone: true, imports: [RouterLink, RouterOutlet, ButtonModule],
  styles: ['h1 { font-size: 2rem; } nav { display: flex; gap: 1rem; }'],
  template: `<h1>Framework compatibility</h1><nav><a routerLink="/">Home</a><a routerLink="/orders/42">Order 42</a></nav>
    <p-button label="Change theme" (onClick)="changeTheme()" />
    <p id="theme">{{theme}}</p><router-outlet />`})
class App {
  theme = 'Aura';
  changeTheme() { this.theme = this.theme === 'Aura' ? 'Lara' : 'Aura'; usePreset(this.theme === 'Aura' ? Aura : Lara); }
}
@Component({standalone: true, template: '<h2 id="view">Order dashboard</h2><p>Open an order to load its separate route.</p>'})
class Home {}
enableProdMode();
await bootstrapApplication(App, {providers: [provideZonelessChangeDetection(), provideAnimationsAsync(),
  {provide: APP_BASE_HREF, useValue: LSF_MOUNT + '/'},
  providePrimeNG({theme: {preset: Aura, options: {darkModeSelector: '.dark'}}}),
  provideRouter([{path: '', component: Home}, {path: 'orders/:id', loadComponent: () => import('./order').then(m => m.Order)}])
]});
