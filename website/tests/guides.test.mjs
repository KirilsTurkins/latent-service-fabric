import assert from 'node:assert/strict';
import {test} from 'node:test';
import sidebars from '../sidebars.ts';

test('current learning and operator guides appear in their task sidebars', () => {
  const expected = {
    learn: ['learn/deliver-and-recover-a-capsule'],
    howTo: [
      'how-to/exercise-provider-failure-and-recovery',
      'how-to/reconcile-a-policy-change',
    ],
    contribute: [
      'operations/maintained-security-monitoring',
      'operations/native-release-promotion',
    ],
    reference: ['phase-2-rollouts', 'phase-2-audit', 'component-development/packaging'],
  };
  const flatten = entries => entries.flatMap(entry => entry.type === 'category' ? flatten(entry.items) : [entry]);
  for (const [group, identifiers] of Object.entries(expected)) {
    for (const identifier of identifiers) {
      assert.ok(flatten(sidebars[group]).some(entry => entry.type === 'doc' && entry.id === identifier), `${identifier} belongs in ${group}`);
      assert.ok(!sidebars.understand.some(entry => entry.type === 'doc' && entry.id === identifier), `${identifier} is a task guide`);
    }
  }
});
