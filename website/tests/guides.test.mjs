import assert from 'node:assert/strict';
import {test} from 'node:test';
import sidebars from '../sidebars.ts';

test('current learning and operator guides appear in their task sidebars', () => {
  const expected = {
    learn: ['learn/deliver-and-recover-a-capsule'],
    howTo: [
      'how-to/exercise-provider-failure-and-recovery',
      'how-to/reconcile-a-policy-change',
      'operations/maintained-security-monitoring',
      'operations/native-release-promotion',
    ],
  };
  for (const [group, identifiers] of Object.entries(expected)) {
    for (const identifier of identifiers) {
      assert.ok(sidebars[group].some(entry => entry.type === 'doc' && entry.id === identifier), `${identifier} belongs in ${group}`);
      assert.ok(!sidebars.understand.some(entry => entry.type === 'doc' && entry.id === identifier), `${identifier} is a task guide`);
    }
  }
});
