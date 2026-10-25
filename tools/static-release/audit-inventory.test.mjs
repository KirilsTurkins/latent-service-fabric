import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp, writeFile, rm} from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {inventoryHeadroom, main} from './audit-headroom.mjs';
import {NativeClient} from './io.mjs';

function sample(changes = {}) {
  return {schemaVersion: 'latent.cli.result.v1', category: 'success', outcomeKnown: true, requestDispatched: true,
    data: {inventory: {node: {id: 'audit-node'}, observedAtUnixMillis: '18446744073709551615',
      topology: {available: true, complete: true, entries: [{name: 'audit-journal', kind: 'store', ownership: 'node-fixed',
        configuredCount: '1', activeCount: null, attributes: {
          profile: 'audit-capacity-v1', measurementStatus: 'available', maximumRecords: '64', maximumDiskBytes: '1048576',
          maximumRecordBytes: '16384', maximumQueuedOperations: '4', maximumQueuedBytes: '16384', maximumQueryOwners: '4',
          audit_retained_records: '0', audit_retained_bytes: '0', audit_reserved_records: '0', audit_reserved_bytes: '0',
          audit_queued_operations: '0', audit_queued_bytes: '0', audit_node_metadata_maximum_bytes: '1048576',
          audit_node_metadata_reserved_bytes: '131072', audit_closed: '0', audit_recovery_pending: '0',
          audit_pending_attempts: '0', audit_previous_session_loss_unknown: '1', audit_unknown_outcomes: '0',
          audit_dropped_observations: '0', audit_unavailable_events: '0', ...changes,
        }}]}}}};
}
const attrs = value => value.data.inventory.topology.entries[0].attributes;

test('native inventory supplies matching limits and original full-width observation time', () => {
  const value = sample({audit_reserved_records: '2', audit_reserved_bytes: '32768'});
  const before = structuredClone(value), report = inventoryHeadroom(value, 'audit-node');
  assert.equal(report.status, 'headroom-observed');
  assert.equal(report.headroom.records, '62'); assert.equal(report.headroom.bytes, '1015808');
  assert.equal(report.budget.criticalRecords, '6'); assert.equal(report.budget.records, '10');
  assert.equal(report.observedAtUnixMillis, '18446744073709551615');
  assert.equal(report.sampleSource, 'node-inventory'); assert.equal(report.sampleFreshness, 'not-established');
  assert.equal(report.reservation, false); assert.equal(report.historyComplete, false);
  assert.deepEqual(value, before);
});
test('missing duplicated unavailable foreign and unsupported inventory never imply free capacity', () => {
  const mutations = [
    value => { value.outcomeKnown = false; },
    value => { value.category = 'platform-failure'; },
    value => { value.data.inventory.node.id = 'foreign-node'; },
    value => { value.data.inventory.observedAtUnixMillis = 42; },
    value => { value.data.inventory.topology.available = false; },
    value => { value.data.inventory.topology.complete = false; },
    value => { value.data.inventory.topology.entries = []; },
    value => { value.data.inventory.topology.entries.push(structuredClone(value.data.inventory.topology.entries[0])); },
    value => { attrs(value).measurementStatus = 'unavailable'; },
    value => { attrs(value).measurementStatus = 'not-configured'; },
    value => { attrs(value).profile = 'unknown'; },
    value => { attrs(value).maximumRecordBytes = '8192'; },
    value => { attrs(value).maximumQueuedBytes = '65536'; },
    value => { attrs(value).maximumRecords = '064'; },
    value => { delete attrs(value).audit_reserved_bytes; },
  ];
  for (const mutate of mutations) {
    const value = sample(); mutate(value);
    const report = inventoryHeadroom(value, 'audit-node');
    assert.equal(report.status, 'unavailable'); assert.equal(report.reservation, false);
  }
  assert.equal(inventoryHeadroom(sample(), 'foreign').reasons[0], 'audit-snapshot-node-mismatch');
  assert.equal(inventoryHeadroom(sample({measurementStatus: 'not-configured'}), 'audit-node').reasons[0], 'audit-owner-not-configured');
});
test('full native record capacity with spare bytes is a blocked advisory read', () => {
  const report = inventoryHeadroom(sample({audit_retained_records: '64', audit_retained_bytes: '4096'}), 'audit-node');
  assert.equal(report.status, 'blocked');
  assert.deepEqual(report.reasons, ['audit-record-headroom-insufficient']);
  assert.equal(report.headroom.bytes, '1044480'); assert.equal(report.budget.bytes, '163840');
});
test('native preflight always performs a fresh bounded node read and preserves caller margins', async () => {
  const client = new NativeClient({node: 'audit-node', auditOptions: {warningPercent: 50, diagnosticRecords: 3}});
  const calls = []; let retained = '32';
  client.call = async args => { calls.push(args); return sample({audit_retained_records: retained}); };
  const first = await client.auditPreflight(1);
  assert.equal(first.status, 'warning'); assert.equal(first.budget.records, '11');
  retained = '64';
  assert.equal((await client.auditPreflight(1)).status, 'blocked');
  assert.deepEqual(calls, [['node', 'get', 'audit-node'], ['node', 'get', 'audit-node']]);
});
test('protected native inventory CLI needs no manually synchronized audit configuration', async () => {
  const directory = await mkdtemp(path.join(os.tmpdir(), 'lsf-audit-inventory-'));
  try {
    const name = path.join(directory, 'inventory.json');
    await writeFile(name, JSON.stringify(sample()), {mode: 0o600});
    const args = ['--inventory', name, '--node', 'audit-node'];
    assert.equal((await main(args)).report.headroom.records, '64');
    assert.match((await main([...args, '--output', 'human'])).output, /6 records/);
    await assert.rejects(main([...args, '--audit-config', name]), /audit-headroom-input-required/);
    await assert.rejects(main(['--inventory', name]), /audit-headroom-input-required/);
  } finally { await rm(directory, {recursive: true, force: true}); }
});
