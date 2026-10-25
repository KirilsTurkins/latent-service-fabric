import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp, writeFile, rm} from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {auditHeadroom, humanHeadroom, main} from './audit-headroom.mjs';

const config = {mode: 'durable'};
function usage(changes = {}) {
  const counters = {retained_records: '0', retained_bytes: '0', reserved_records: '0', reserved_bytes: '0',
    queued_operations: '0', queued_bytes: '0', node_metadata_maximum_bytes: '8388608',
    node_metadata_reserved_bytes: '131072', closed: '0', recovery_pending: '0', pending_attempts: '0',
    previous_session_loss_unknown: '1', unknown_outcomes: '0', dropped_observations: '0', unavailable_events: '0', ...changes};
  return {scope: 'node', unavailable: [], counters: Object.fromEntries(Object.entries(counters).map(([key, value]) => ['audit_' + key, value]))};
}

test('renewal planning charges six critical records plus explicit diagnostics and competitors', () => {
  const report = auditHeadroom(usage(), config);
  assert.equal(report.status, 'headroom-observed');
  assert.equal(report.budget.criticalRecords, '6');
  assert.equal(report.budget.records, '10');
  assert.equal(report.budget.bytes, '163840');
  assert.equal(report.planning.cyclesAtBudget, '409');
  assert.equal(report.planning.minutesAtBudget, '4090');
  assert.equal(report.advisory, true);
  assert.equal(report.reservation, false);
  assert.equal(report.executionPermission, false);
  assert.equal(report.sampleFreshness, 'not-established');
  assert.equal(report.filesystemCapacity, 'not-observed');
  assert.equal(report.historyComplete, false);
  assert.equal(report.planning.competingTrafficBoundedByThisPlan, false);
});

test('record exhaustion is blocked even with spare byte capacity', () => {
  const report = auditHeadroom(usage({retained_records: '4096', retained_bytes: '4299161'}), config);
  assert.equal(report.status, 'blocked');
  assert.deepEqual(report.reasons, ['audit-record-headroom-insufficient']);
  assert.equal(report.headroom.records, '0');
  assert.equal(report.headroom.bytes, String(67108864 - 4299161));
  assert.equal(report.planning.cyclesAtBudget, '0');
});

test('charged reservations can block a cycle before retained records reach the cap', () => {
  const report = auditHeadroom(usage({retained_records: '4086', reserved_records: '2', reserved_bytes: '32768', pending_attempts: '1'}), config);
  assert.equal(report.headroom.records, '8');
  assert.equal(report.headroom.bytes, '67076096');
  assert.equal(report.charged.reservedRecords, '2');
  assert.ok(report.reasons.includes('audit-critical-pending'));
  assert.ok(report.reasons.includes('audit-record-headroom-insufficient'));
});

test('byte, queue, metadata and storage pressure are independent', () => {
  const cases = [
    [{retained_bytes: String(67108864 - 163839)}, 'audit-byte-headroom-insufficient'],
    [{queued_operations: '64'}, 'audit-queue-operation-pressure'],
    [{queued_bytes: '262144'}, 'audit-queue-byte-pressure'],
    [{node_metadata_reserved_bytes: '8388608'}, 'audit-metadata-pressure'],
    [{closed: '1'}, 'audit-closed'],
    [{recovery_pending: '1'}, 'audit-recovery-pending'],
  ];
  for (const [values, reason] of cases) {
    const report = auditHeadroom(usage(values), config);
    assert.equal(report.status, 'blocked');
    assert.ok(report.reasons.includes(reason), reason);
  }
  const smallQueue = auditHeadroom(usage({queued_bytes: '1'}), {...config, queuedOperations: 1});
  assert.ok(smallQueue.reasons.includes('audit-queue-byte-pressure'));
  assert.equal(smallQueue.headroom.queuedBytes, '16383');
});

test('warning thresholds include reservations and remain useful without audit writes', () => {
  const sample = usage({retained_records: '2047', reserved_records: '1', reserved_bytes: '16384'});
  const before = structuredClone(sample);
  const report = auditHeadroom(sample, config, {warningPercent: 50});
  assert.equal(report.status, 'warning');
  assert.ok(report.warnings.includes('audit-record-warning'));
  assert.deepEqual(sample, before);
  assert.match(humanHeadroom(report), /no capacity has been reserved/);
  assert.match(humanHeadroom(report), /not a lifetime guarantee/);
});

test('scope, unavailable counters and malformed u64 values never become free capacity', () => {
  for (const sample of [null, {...usage(), scope: 'tenant'}, {...usage(), unavailable: ['audit-owner-not-configured']},
    usage({retained_records: undefined}), usage({retained_records: 0}), usage({retained_records: '00'}),
    usage({retained_records: '-1'}), usage({retained_records: '18446744073709551616'}),
    usage({previous_session_loss_unknown: '2'}), usage({node_metadata_maximum_bytes: '0', node_metadata_reserved_bytes: '1'})]) {
    const report = auditHeadroom(sample, config);
    assert.equal(report.status, 'unavailable');
    assert.equal(report.reservation, false);
    assert.equal(report.historyComplete, false);
  }
  assert.equal(auditHeadroom(usage({retained_records: '4097'}), config).reasons[0], 'audit-snapshot-limit-mismatch');
  assert.equal(auditHeadroom(usage({reserved_bytes: '67108865'}), config).reasons[0], 'audit-snapshot-limit-mismatch');
});

test('loss and durable unknown counts survive independently of available headroom', () => {
  const report = auditHeadroom(usage({unknown_outcomes: '18446744073709551615', dropped_observations: '7', unavailable_events: '9'}), config);
  assert.equal(report.status, 'headroom-observed');
  assert.deepEqual(report.coverage, {unknownOutcomes: '18446744073709551615', droppedObservations: '7',
    unavailableEvents: '9', previousSessionLossUnknown: true});
  assert.equal(report.historyComplete, false);
});

test('route counts, cadence and finite options are validated without coercing null defaults', () => {
  const report = auditHeadroom(usage(), config, {routePairs: 8, diagnosticRecords: 0, competingOperations: 0, cadenceMinutes: 1});
  assert.equal(report.budget.criticalRecords, '34');
  assert.equal(report.budget.records, '34');
  assert.equal(report.budget.bytes, String(34 * 16384));
  for (const options of [{routePairs: 0}, {routePairs: 9}, {diagnosticRecords: 257}, {competingOperations: 65},
    {warningPercent: 0}, {warningPercent: 101}, {cadenceMinutes: 1441}, {routePairs: null}, {extra: 1}]) {
    assert.throws(() => auditHeadroom(usage(), config, options), /audit-planning-option-bound/);
  }
  for (const settings of [{mode: 'disabled'}, {...config, records: null}, {...config, records: 16385},
    {...config, diskBytes: 32767}, {...config, extra: 1}]) assert.throws(() => auditHeadroom(usage(), settings));
});

test('protected-file CLI accepts the native usage envelope and rejects input coercion', async () => {
  const directory = await mkdtemp(path.join(os.tmpdir(), 'lsf-audit-headroom-'));
  try {
    const sample = path.join(directory, 'usage.json'), settings = path.join(directory, 'audit.json');
    await writeFile(sample, JSON.stringify({schemaVersion: 'latent.cli.result.v1', category: 'success',
      outcomeKnown: true, data: {nodeUsage: usage()}}), {mode: 0o600});
    await writeFile(settings, JSON.stringify(config), {mode: 0o600});
    const args = ['--usage', sample, '--audit-config', settings];
    const result = await main(args);
    assert.equal(JSON.parse(result.output).budget.criticalRecords, '6');
    assert.match((await main([...args, '--output', 'human'])).output, /Advisory only/);
    await assert.rejects(main([...args, '--route-pairs', '01']), /audit-planning-option-bound/);
    await assert.rejects(main([...args, '--unknown', '1']));
  } finally { await rm(directory, {recursive: true, force: true}); }
});
