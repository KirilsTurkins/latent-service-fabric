import test from 'node:test';
import assert from 'node:assert/strict';
import {manifests, plan, validateJournal, equal} from './model.mjs';
import {reconcile} from './reconcile.mjs';

const publication = digit => 'publication:sha256:' + digit.repeat(64);
const intent = (digit = 'a') => ({schemaVersion: 'latent.static.route-set.v1', tenant: 'example', publication: publication(digit),
  routes: [{get: 'docs-get', head: 'docs-head', scheme: 'https', host: 'docs.example.test', path: '/docs', pathMatch: 'prefix'}]});
const success = data => ({schemaVersion: 'latent.cli.result.v1', category: 'success', requestDispatched: true, outcomeKnown: true, data});

// Fault-oriented model tests supplement the real CLI/node workflow. They do not
// qualify a managed host, filesystem or network environment.
class Catalog {
  state = 0n; rows = new Map(); receipts = new Map(); writes = []; eligibility = 'ELIGIBLE'; before = null; lost = false;
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
    await this.before?.(this, manifest, attempt);
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
