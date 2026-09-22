import {Component, inject} from '@angular/core';
import {AsyncPipe} from '@angular/common';
import {ActivatedRoute} from '@angular/router';
import {map} from 'rxjs';

@Component({selector: 'lsf-order', imports: [AsyncPipe], template: '<h2 id="view">Order {{id | async}}</h2>'})
export class Order {
  readonly id = inject(ActivatedRoute).paramMap.pipe(map(params => params.get('id')));
}
