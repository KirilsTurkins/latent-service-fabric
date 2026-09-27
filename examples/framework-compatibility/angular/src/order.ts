import {Component, inject} from '@angular/core';
import {ActivatedRoute} from '@angular/router';
import {ButtonModule} from 'primeng/button';

@Component({standalone: true, imports: [ButtonModule], styles: ['#view { color: rgb(24, 64, 100); }'],
  template: '<h2 id="view">Order {{id}}</h2><p-button label="Confirm order" (onClick)="confirmed = true" /><p id="confirmation">{{confirmed ? "Confirmed" : "Pending"}}</p>'})
export class Order {
  id = inject(ActivatedRoute).snapshot.paramMap.get('id');
  confirmed = false;
}
