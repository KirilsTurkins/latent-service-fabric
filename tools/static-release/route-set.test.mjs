import test from 'node:test';
import assert from 'node:assert/strict';
import {manifests, plan, validateJournal, equal} from './model.mjs';
import {reconcile} from './reconcile.mjs';

const publication = digit => 'publication:sha256:' + digit.repeat(64);
const intent = (digit = 'a') => ({schemaVersion: 'latent.static.route-set.v1', tenant: 'example', publication: publication(digit),
  routes: [{get: 'docs-get', head: 'docs-head', scheme: 'https', host: 'docs.example.test', path: '/docs', pathMatch: 'prefix'}]});
const success = data => ({schemaVersion: 'latent.cli.result.v1', category: 'success', requestDispatched: true, outcomeKnown: true, data});
const capacity = status => ({schemaVersion: 'latent.static.audit-headroom.v1', status,
  advisory: true, reservation: false, executionPermission: false});
const rejected = (known = true, reason = 'audit-capacity') => ({...success({auditAck: {status: 'audit-unavailable'}}),
  category: 'platform-failure', outcomeKnown: known, error: {code: 'resource-exhausted',
    details: [{kind: 'audit-journal', fields: {reason}}]}});

// Fault-oriented model tests supplement the real CLI/node workflow. They do not
// qualify a managed host, filesystem or network environment.
class Catalog {
  state = 0n; rows = new Map(); receipts = new Map(); writes = []; eligibility = 'ELIGIBLE'; before = null; lost = false;
  pressure = null; preflights = 0;
  async auditPreflight() { this.preflights++; return capacity(this.pressure ?? 'headroom-observed'); }
  async call(args) {
    if (args[0] === 'web') return success({record: {publication: {id: args[3], tenant: 'example'}},
      eligibility: 'RELEASE_LIVE_ELIGIBILITY_' + this.eligibility,
      eligibilityReason: 'RELEASE_ELIGIBILITY_REASON_' + (this.eligibility === 'ELIGIBLE' ? 'VERIFIED' : 'REVOKED')});
    if (args[1] === 'get') return {...success({trigger: this.rows.get(args[2]) ?? null, stateVersion: String(this.state), durability: 'confirmed'}),
      category: this.rows.has(args[2]) ? 'success' : 'not-found'};
    if (args[1] === 'operation') {
      const receipt = this.receipts.get(args[2]);
      return {...success({disposition: receipt ? 'found' : 'unknown', receipt: receipt ?? null}), outcomeKnown: !!receipt};
    }
    assert.fail('unexpected read');
  }
  async apply(manifest, attempt) {
    this.writes.push(structuredClone({manifest, attempt}));
    const refusal = await this.before?.(this, manifest, attempt);
    if (refusal) return refusal;
    if (attempt.stateVersion !== String(this.state) || attempt.generation !== (this.rows.get(manifest.metadata.name)?.generation ?? '0')) {
      return {...success({}), category: 'platform-failure', error: {code: 'state-conflict'}};
    }
    const generation = String(++this.state);
    this.rows.set(manifest.metadata.name, {manifest: structuredClone(manifest), generation});
    const receipt = {formatVersion: 2, operationId: attempt.id, tenant: manifest.metadata.tenant, triggerId: manifest.metadata.name,
      action: 'TRIGGER_OPERATION_ACTION_APPLY', expectedGeneration: attempt.generation, expectedStateVersion: attempt.stateVersion,
      objectGeneration: generation, stateVersion: generation, target: {kind: 'static-web', publication: {id: manifest.spec.target.publication, tenant: manifest.metadata.tenant}}};
    this.receipts.set(attempt.id, receipt);
    if (this.lost) { this.lost = false; return {...success({}), outcomeKnown: false, category: 'transport-failure'}; }
    return success({receipt, durability: 'confirmed'});
  }
}
function storage() {
  let durable;
  return {save: async value => { durable = structuredClone(value); }, load: () => structuredClone(durable)};
}

test('durable GET interruption resumes HEAD and read-only status creates no operation', async () => {
  const client = new Catalog(), store = storage(), journal = await plan(client, intent(), 'connection');
  validateJournal(journal, 'connection');
  assert.equal((await reconcile(client, journal, store.save, 0)).status, 'partial');
  assert.equal(journal.rows[0].attempts.length, 0);
  assert.equal((await reconcile(client, journal, store.save, 1)).status, 'partial');
  assert.equal(client.rows.get('docs-get').manifest.spec.target.publication, publication('a'));
  assert.equal(client.rows.has('docs-head'), false);
  assert.equal((await reconcile(client, store.load(), store.save)).status, 'complete');
  assert.equal(client.writes.length, 2);
});
test('lost committed reply is recovered by receipt and live identity without replay', async () => {
  const client = new Catalog(), store = storage(), journal = await plan(client, intent(), 'connection');
  client.lost = true;
  assert.equal((await reconcile(client, journal, store.save)).status, 'uncertain');
  assert.equal(store.load().rows[0].attempts[0].status, 'pending');
  assert.equal((await reconcile(client, store.load(), store.save)).status, 'complete');
  assert.equal(client.writes.length, 2);
  assert.equal(new Set(client.writes.map(row => row.attempt.id)).size, 2);
});
test('unrelated concurrent mutation permits fresh guarded attempt and preserves unrelated route', async () => {
  const client = new Catalog(), store = storage(), journal = await plan(client, intent(), 'connection');
  client.before = async catalog => {
    catalog.before = null;
    catalog.rows.set('other', {manifest: {retained: true}, generation: String(++catalog.state)});
  };
  assert.equal((await reconcile(client, journal, store.save)).status, 'complete');
  assert.deepEqual(client.rows.get('other'), {manifest: {retained: true}, generation: '1'});
  assert.equal(client.writes.length, 3);
  assert.notEqual(client.writes[0].attempt.id, client.writes[1].attempt.id);
  assert.equal(client.writes[1].attempt.stateVersion, '1');
});
test('same-route replacement and retained historical success never authorize overwrite', async () => {
  const client = new Catalog(), store = storage(), journal = await plan(client, intent(), 'connection');
  await reconcile(client, journal, store.save, 1);
  const replacement = manifests(intent('b'))[0];
  client.rows.set('docs-get', {manifest: replacement, generation: String(++client.state)});
  const result = await reconcile(client, store.load(), store.save);
  assert.equal(result.status, 'partial'); assert.equal(result.reason, 'confirmed-route-changed-no-overwrite');
  assert.equal(client.writes.length, 1);
  assert.equal(equal(client.rows.get('docs-get').manifest, replacement), true);
});
test('evicted UNKNOWN remains uncertain even when the desired GET is currently visible', async () => {
  const client = new Catalog(), store = storage(), journal = await plan(client, intent(), 'connection');
  client.lost = true;
  await reconcile(client, journal, store.save);
  client.receipts.clear();
  const result = await reconcile(client, store.load(), store.save);
  assert.equal(result.status, 'uncertain'); assert.equal(result.reason, 'receipt-unavailable-no-replay');
  assert.equal(client.writes.length, 1);
});
test('rollback is a fresh plan and current denial blocks writes despite historic receipts', async () => {
  const client = new Catalog(), store = storage();
  for (const digit of ['a', 'b', 'a']) {
    const journal = await plan(client, intent(digit), 'connection');
    assert.equal((await reconcile(client, journal, store.save)).status, 'complete');
  }
  assert.equal(client.writes.length, 6);
  assert.equal(new Set(client.writes.map(row => row.attempt.id)).size, 6);
  const journal = await plan(client, intent('b'), 'connection');
  client.eligibility = 'DENIED';
  assert.equal((await reconcile(client, journal, store.save)).status, 'failed');
  assert.equal(client.writes.length, 6);
});
test('conflict attempts are finite and changed journal intent or connection fails closed', async () => {
  const client = new Catalog(), store = storage(), journal = await plan(client, intent(), 'connection');
  assert.throws(() => validateJournal(journal, 'another-node'), /journal-identity/);
  const changed = structuredClone(journal); changed.intent.publication = publication('b');
  assert.throws(() => validateJournal(changed, 'connection'), /journal-identity/);
  client.before = async catalog => { catalog.state++; };
  const result = await reconcile(client, journal, store.save);
  assert.equal(result.reason, 'conflict-attempt-bound'); assert.equal(client.writes.length, 4);
});
test('operator intent is finite, complete GET/HEAD pairs and preserves current route ownership', async () => {
  const client = new Catalog();
  const base = intent();
  for (const change of [value => value.routes[0].head = value.routes[0].get,
    value => value.routes[0].host = 'DOCS.example.test', value => value.routes[0].path = '/docs/../api',
    value => value.routes[0].path = '/_lsf/assets', value => value.extra = true,
    value => value.routes = Array(9).fill(value.routes[0])]) {
    const value = structuredClone(base); change(value); assert.throws(() => manifests(value));
  }
  const previous = manifests(base)[0]; previous.spec.configuration.path = '/another-owner';
  client.rows.set('docs-get', {manifest: previous, generation: '1'}); client.state = 1n;
  await assert.rejects(plan(client, base, 'connection'), /route-ownership-changed/);
});

test('blocked or unavailable preflight creates no operation and changes no route', async () => {
  for (const pressure of ['blocked', 'unavailable']) {
    const client = new Catalog(), store = storage(), journal = await plan(client, intent(), 'connection');
    client.pressure = pressure;
    const result = await reconcile(client, journal, store.save);
    assert.equal(result.status, 'failed');
    assert.equal(result.reason, 'audit-preflight-' + pressure);
    assert.equal(result.writes, 0); assert.equal(client.writes.length, 0); assert.equal(client.rows.size, 0);
    assert.deepEqual(store.load().rows.map(row => row.attempts), [[], []]);
    assert.equal(store.load().auditCapacity.reservation, false);
    client.pressure = null;
    assert.equal((await reconcile(client, store.load(), store.save)).status, 'complete');
  }
});
test('pressure between GET and HEAD preserves exact committed progress for explicit continuation', async () => {
  const client = new Catalog(), store = storage(), journal = await plan(client, intent(), 'connection');
  client.before = async catalog => { catalog.pressure = 'blocked'; };
  const partial = await reconcile(client, journal, store.save);
  assert.equal(partial.status, 'partial'); assert.equal(partial.reason, 'audit-preflight-blocked');
  assert.equal(client.writes.length, 1); assert.equal(client.rows.has('docs-head'), false);
  const original = store.load().rows[0].attempts[0];
  assert.equal(original.status, 'confirmed');
  client.before = null; client.pressure = null;
  assert.equal((await reconcile(client, store.load(), store.save)).status, 'complete');
  assert.equal(client.writes.length, 2);
  assert.deepEqual(store.load().rows[0].attempts, [original]);
});
test('an affirmative first audit rejection survives recovery and requires an explicit new plan', async () => {
  const client = new Catalog(), store = storage(), journal = await plan(client, intent(), 'connection');
  client.before = async () => rejected();
  const result = await reconcile(client, journal, store.save);
  assert.equal(result.status, 'failed'); assert.equal(result.reason, 'audit-capacity');
  assert.equal(client.rows.size, 0); assert.equal(client.state, 0n);
  const operation = result.routes[0].operations[0];
  assert.equal(operation.status, 'rejected'); assert.equal(operation.auditReason, 'audit-capacity');
  assert.equal(operation.auditAck.status, 'audit-unavailable');
  assert.equal(operation.nextAction, 'restore-audit-headroom-then-explicit-new-plan');
  assert.equal(operation.id, client.writes[0].attempt.id);
  assert.equal(operation.expectedStateVersion, '0');
  client.before = null;
  const recovery = await reconcile(client, store.load(), store.save);
  assert.equal(recovery.reason, 'previous-audit-rejection-new-plan-required');
  assert.equal(client.writes.length, 1);
  const fresh = await plan(client, intent(), 'connection');
  assert.equal((await reconcile(client, fresh, store.save)).status, 'complete');
  assert.notEqual(fresh.rows[0].attempts[0].id, operation.id);
});
test('affirmative HEAD rejection preserves GET receipt and does not retry after headroom returns', async () => {
  const client = new Catalog(), store = storage(), journal = await plan(client, intent(), 'connection');
  client.before = async (_catalog, manifest) => manifest.metadata.name === 'docs-head' ? rejected() : null;
  const result = await reconcile(client, journal, store.save);
  assert.equal(result.status, 'partial'); assert.equal(client.writes.length, 2);
  const retained = store.load();
  assert.equal(retained.rows[0].attempts[0].status, 'confirmed');
  assert.equal(retained.rows[1].attempts[0].status, 'rejected');
  assert.equal(client.rows.has('docs-head'), false);
  client.before = null;
  assert.equal((await reconcile(client, retained, store.save)).reason, 'previous-audit-rejection-new-plan-required');
  assert.equal(client.writes.length, 2);
});
test('unknown exhaustion and postcommit details stay pending despite an audit reason', async () => {
  for (const response of [rejected(false), {...rejected(), data: {receipt: {unvalidated: true}}},
    {...rejected(), error: {code: 'resource-exhausted', details: [
      {kind: 'audit-journal', fields: {reason: 'audit-capacity'}},
      {kind: 'deployment-mutation', fields: {committed: 'true'}}]}}]) {
    const client = new Catalog(), store = storage(), journal = await plan(client, intent(), 'connection');
    client.before = async () => response;
    assert.equal((await reconcile(client, journal, store.save)).status, 'uncertain');
    const original = store.load().rows[0].attempts[0];
    assert.equal(original.status, 'pending');
    client.before = null;
    assert.equal((await reconcile(client, store.load(), store.save)).reason, 'receipt-unavailable-no-replay');
    assert.equal(client.writes.length, 1);
    assert.equal(store.load().rows[0].attempts[0].id, original.id);
  }
});
test('read-only receipt recovery is not gated by unavailable headroom', async () => {
  const client = new Catalog(), store = storage(), journal = await plan(client, intent(), 'connection');
  client.lost = true;
  await reconcile(client, journal, store.save);
  const original = store.load().rows[0].attempts[0].id, calls = client.preflights;
  client.pressure = 'unavailable';
  const result = await reconcile(client, store.load(), store.save, 0);
  assert.equal(result.status, 'partial'); assert.equal(client.preflights, calls);
  assert.equal(store.load().rows[0].attempts[0].id, original);
  assert.equal(store.load().rows[0].attempts[0].status, 'confirmed');
  assert.equal(client.writes.length, 1);
});
test('a later pending HEAD remains uncertain when authorization changes while rechecking GET', async () => {
  const client = new Catalog(), store = storage(), journal = await plan(client, intent(), 'connection');
  client.before = async (catalog, manifest) => { if (manifest.metadata.name === 'docs-head') catalog.lost = true; };
  assert.equal((await reconcile(client, journal, store.save)).status, 'uncertain');
  const original = store.load().rows[1].attempts[0].id;
  const call = client.call.bind(client); let observations = 0;
  client.call = async args => {
    if (args[0] === 'web' && ++observations === 2) client.eligibility = 'DENIED';
    return call(args);
  };
  const result = await reconcile(client, store.load(), store.save);
  assert.equal(result.status, 'uncertain'); assert.equal(result.reason, 'publication-not-currently-eligible');
  assert.equal(result.routes[1].pendingOperation, original); assert.equal(client.writes.length, 2);
});
