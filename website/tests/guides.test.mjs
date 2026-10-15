import assert from 'node:assert/strict';
import {test} from 'node:test';
import sidebars from '../sidebars.ts';
import discovery from '../plugins/discovery.mjs';
import {prepare} from '../lib/prepare.mjs';

test('current learning and operator guides appear in their task sidebars', () => {
  const expected = {
    learn: ['learn/deliver-and-recover-a-capsule'],
    howTo: [
      'how-to/reconcile-a-policy-change',
      'how-to/add-application-libraries', 'how-to/inspect-a-composition', 'operations/transaction-recovery',
      'component-development/c-dependencies', 'component-development/java-dependencies', 'component-development/dotnet-dependencies',
    ],
    contribute: [
      'how-to/exercise-provider-failure-and-recovery',
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

test('all six dependency workflows and original recovery are discoverable as tasks', async () => {
  let catalogue;
  await discovery({}, {}, prepare()).contentLoaded({actions: {setGlobalData(value) { catalogue = value.guides; }}});
  for (const language of ['rust', 'c', 'typescript', 'go', 'java', 'dotnet']) {
    const guide = catalogue.find(item => item.id === `libraries-${language}`);
    assert.ok(guide, language);
    assert.equal(guide.languages.length, 1);
    assert.equal(guide.pages.length, 1);
    assert.ok(guide.pages[0].route.startsWith('/docs/component-development/'));
  }
  assert.ok(catalogue.find(item => item.id === 'inspect-composition').pages.some(page => page.route === '/docs/how-to/inspect-a-composition/'));
  assert.ok(catalogue.find(item => item.id === 'transaction-recovery').pages.some(page => page.route === '/docs/operations/transaction-recovery/'));
});

test('engineering records stay out of the contributor setup path', () => {
  const flatten = entries => entries.flatMap(entry => entry.type === 'category' ? flatten(entry.items) : [entry]);
  for (const id of ['development/engineering-records',
    'development/documentation-audit-2026-10-14']) {
    assert.ok(flatten(sidebars.records).some(entry => entry.id === id), id);
    assert.ok(!flatten(sidebars.contribute).some(entry => entry.id === id), id);
  }
});
