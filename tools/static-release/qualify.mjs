import assert from 'node:assert/strict';
import path from 'node:path';
import {connection, durableWrite, readJson} from './io.mjs';
import {plan, observe} from './model.mjs';
import {reconcile} from './reconcile.mjs';
import {main} from './route-set.mjs';

const [cli, config, node, directory, host, publicationA, publicationB] = process.argv.slice(2);
const intent = (name, publication) => ({schemaVersion: 'latent.static.route-set.v1', tenant: 'tests', publication,
  routes: [{get: name + '-get', head: name + '-head', scheme: 'http', host, path: '/' + name, pathMatch: 'prefix'}]});
function options(name) { return {cli, config, node, profile: 'operator', journal: path.join(directory, name + '.json'), deadlineSeconds: 300}; }
async function execute(command, name, value, maximumWrites) {
  const selected = options(name);
  const args = [command, '--cli', cli, '--config', config, '--node', node, '--profile', 'operator', '--journal', selected.journal, '--deadline-seconds', '300'];
  if (value) { const file = selected.journal + '.intent'; await durableWrite(file, value, true); args.push('--intent', file); }
  if (maximumWrites) args.push('--maximum-writes', String(maximumWrites));
  return main(args);
}
async function prepareFault(name, publication) {
  const selected = options(name), {client, binding} = await connection(selected, 'tests');
  const journal = await plan(client, intent(name, publication), binding);
  await durableWrite(selected.journal, journal, true);
  return {selected, client, journal, save: value => durableWrite(selected.journal, value)};
}

// Every mutation below uses the real released command surface and the running
// node. Deliberate client-side loss/interleaving happens only after real calls.
await execute('plan', 'initial', intent('reconcile', publicationA));
assert.equal((await execute('apply', 'initial')).status, 'complete');
await execute('plan', 'cutover', intent('reconcile', publicationB));
assert.equal((await execute('apply', 'cutover', null, 1)).status, 'partial');
const {client} = await connection(options('cutover'), 'tests');
assert.equal((await observe(client, 'reconcile-get', 'tests')).manifest.spec.target.publication, publicationB);
assert.equal((await observe(client, 'reconcile-head', 'tests')).manifest.spec.target.publication, publicationA);
assert.equal((await execute('status', 'cutover')).status, 'partial');
assert.equal((await execute('apply', 'cutover')).status, 'complete');

const lost = await prepareFault('lost-reply', publicationB);
const originalApply = lost.client.apply.bind(lost.client);
lost.client.apply = async (...args) => {
  const committed = await originalApply(...args); assert.equal(committed.category, 'success');
  throw new Error('qualification-lost-successful-response');
};
assert.equal((await reconcile(lost.client, lost.journal, lost.save)).status, 'uncertain');
assert.equal((await execute('apply', 'lost-reply')).status, 'complete');
assert.deepEqual((await readJson(lost.selected.journal, true)).rows.map(row => row.attempts.length), [1, 1]);

const concurrent = await prepareFault('concurrent', publicationB);
const applyConcurrent = concurrent.client.apply.bind(concurrent.client);
let changed = false;
concurrent.client.apply = async (...args) => {
  if (!changed) {
    changed = true;
    await execute('plan', 'unrelated', intent('unrelated', publicationA));
    assert.equal((await execute('apply', 'unrelated')).status, 'complete');
  }
  return applyConcurrent(...args);
};
assert.equal((await reconcile(concurrent.client, concurrent.journal, concurrent.save)).status, 'complete');
assert.equal(concurrent.journal.rows[0].attempts[0].code, 'state-conflict');
assert.equal((await observe(client, 'unrelated-get', 'tests')).manifest.spec.target.publication, publicationA);

await execute('plan', 'same-route-stale', intent('reconcile', publicationA));
await execute('plan', 'same-route-winner', intent('reconcile', publicationA));
assert.equal((await execute('apply', 'same-route-winner')).status, 'complete');
assert.equal((await execute('apply', 'same-route-stale')).reason, 'route-changed-no-overwrite');

const evicted = await prepareFault('evicted', publicationB);
const applyEvicted = evicted.client.apply.bind(evicted.client);
evicted.client.apply = async (...args) => {
  assert.equal((await applyEvicted(...args)).category, 'success');
  throw new Error('qualification-lost-successful-response');
};
assert.equal((await reconcile(evicted.client, evicted.journal, evicted.save)).status, 'uncertain');
for (let index = 0; index < 65; index++) {
  const row = await observe(client, 'unrelated-get', 'tests');
  const result = await client.apply(row.manifest, {id: 'eviction-' + index, generation: row.generation, stateVersion: row.stateVersion});
  assert.equal(result.category, 'success'); assert.equal(result.outcomeKnown, true);
}
assert.equal((await execute('apply', 'evicted')).reason, 'receipt-unavailable-no-replay');
assert.equal((await observe(client, 'evicted-head', 'tests')).manifest, null);

// A rollback uses another explicit journal and another set of guarded IDs.
await execute('plan', 'advance-again', intent('reconcile', publicationB));
assert.equal((await execute('apply', 'advance-again')).status, 'complete');
await execute('plan', 'rollback', intent('reconcile', publicationA));
assert.equal((await execute('apply', 'rollback')).status, 'complete');
const current = await client.call(['web', 'get', '--publication', publicationA]);
assert.equal((await client.call(['web', 'retire', '--publication', publicationA, '--operation-id', 'reconciliation-retire',
  '--expected-generation', current.data.record.generation])).category, 'success');
const denied = await execute('apply', 'rollback');
assert.equal(denied.reason, 'publication-not-currently-eligible');

console.log(JSON.stringify({schemaVersion: 'latent.static.route-qualification.v1', passed: true,
  actualNativeCliAndNode: true, interruptedPair: true, lostSuccessfulReplyRecoveredWithoutReplay: true,
  unrelatedConflictRecovered: true, sameRouteConflictPreserved: true, evictedUnknownNotReplayed: true,
  explicitRollback: true, retiredHistoricalSuccessDenied: true}));
