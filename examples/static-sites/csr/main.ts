import {Component} from '@angular/core';
import {APP_BASE_HREF} from '@angular/common';
import {bootstrapApplication} from '@angular/platform-browser';
import {provideRouter, RouterLink, RouterOutlet} from '@angular/router';
import {BUILD_VERSION} from './version.js';

@Component({selector: 'lsf-home', template: '<h2 id="view">Orders home</h2>'})
class Home {}

@Component({selector: 'lsf-static-app', imports: [RouterLink, RouterOutlet], template: `
  <h1>Static orders <span id="version">{{version}}</span></h1>
  <nav><a id="home" routerLink="/">Home</a> <a id="order42" routerLink="/orders/42">Order 42</a>
    <a id="order73" routerLink="/orders/73">Order 73</a></nav>
  <router-outlet />`})
class Application { readonly version = BUILD_VERSION; }

bootstrapApplication(Application, {providers: [
  {provide: APP_BASE_HREF, useValue: '/'},
  provideRouter([{path: '', component: Home},
    {path: 'orders/:id', loadComponent: () => import('./order.js').then(module => module.Order)}]),
]}).catch(() => { document.documentElement.dataset['boot'] = 'failed'; });
