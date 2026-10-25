// Pure bounded advisory arithmetic shared by offline reports and live preflight.
import {requireValue} from './model.mjs';

const RECORD_BYTES = 16384n, U64 = 18446744073709551615n;
const common = () => ({schemaVersion: 'latent.static.audit-headroom.v1', advisory: true,
  reservation: false, executionPermission: false, sampleFreshness: 'not-established',
  filesystemCapacity: 'not-observed', historyComplete: false});
function integer(value, minimum, maximum) {
  requireValue(Number.isSafeInteger(value) && value >= minimum && value <= maximum, 'audit-planning-option-bound');
  return BigInt(value);
}
const supplied = (object, key, fallback) => Object.hasOwn(object, key) ? object[key] : fallback;
function settings(audit, options) {
  requireValue(audit && typeof audit === 'object' && !Array.isArray(audit)
    && audit.mode === 'durable' && Object.keys(audit).every(key =>
      ['mode', 'records', 'diskBytes', 'queuedOperations', 'queryOwners'].includes(key)), 'audit-settings-invalid');
  requireValue(options && typeof options === 'object' && !Array.isArray(options)
    && Object.keys(options).every(key => ['routePairs', 'diagnosticRecords', 'competingOperations',
      'warningPercent', 'cadenceMinutes'].includes(key)), 'audit-planning-option-bound');
  integer(supplied(audit, 'queryOwners', 4), 1, 16);
  return {
    records: integer(supplied(audit, 'records', 4096), 2, 16384),
    bytes: integer(supplied(audit, 'diskBytes', 67108864), 32768, 268435456),
    operations: integer(supplied(audit, 'queuedOperations', 64), 1, 256),
    routePairs: integer(supplied(options, 'routePairs', 1), 1, 8),
    diagnostics: integer(supplied(options, 'diagnosticRecords', 2), 0, 256),
    competitors: integer(supplied(options, 'competingOperations', 1), 0, 64),
    warningPercent: integer(supplied(options, 'warningPercent', 80), 1, 100),
    cadence: integer(supplied(options, 'cadenceMinutes', 10), 1, 1440),
  };
}
function unsigned(value) {
  requireValue(typeof value === 'string' && /^(0|[1-9][0-9]{0,19})$/.test(value)
    && BigInt(value) <= U64, 'audit-snapshot-invalid');
  return BigInt(value);
}
function readCounter(counters, name) {
  requireValue(Object.hasOwn(counters, 'audit_' + name), 'audit-snapshot-unavailable');
  return unsigned(counters['audit_' + name]);
}
function remaining(limit, charged) {
  requireValue(charged <= limit, 'audit-snapshot-limit-mismatch');
  return limit - charged;
}
function unavailable(error) {
  const reason = ['audit-snapshot-unavailable', 'audit-snapshot-invalid', 'audit-snapshot-limit-mismatch',
    'audit-owner-not-configured', 'audit-snapshot-node-mismatch'].includes(error?.message)
    ? error.message : 'audit-snapshot-invalid';
  return {...common(), status: 'unavailable', reasons: [reason], warnings: [],
    nextAction: 'obtain-complete-node-scoped-audit-snapshot-and-matching-settings'};
}

export function auditHeadroom(usage, audit, options = {}) {
  const limits = settings(audit, options);
  try {
    requireValue(usage?.scope === 'node' && usage.counters && typeof usage.counters === 'object'
      && !Array.isArray(usage.counters) && Object.keys(usage.counters).length <= 256
      && Array.isArray(usage.unavailable) && usage.unavailable.length <= 32
      && !usage.unavailable.includes('audit-owner-not-configured'), 'audit-snapshot-unavailable');
    const get = name => readCounter(usage.counters, name);
    const retainedRecords = get('retained_records'), retainedBytes = get('retained_bytes');
    const reservedRecords = get('reserved_records'), reservedBytes = get('reserved_bytes');
    const queuedOperations = get('queued_operations'), queuedBytes = get('queued_bytes');
    const metadataMaximum = get('node_metadata_maximum_bytes'), metadataCharged = get('node_metadata_reserved_bytes');
    const closed = get('closed'), recovery = get('recovery_pending'), pending = get('pending_attempts');
    const previousLoss = get('previous_session_loss_unknown');
    requireValue([closed, recovery, pending, previousLoss].every(value => value <= 1n), 'audit-snapshot-invalid');
    const unknown = get('unknown_outcomes'), dropped = get('dropped_observations'), storageUnavailable = get('unavailable_events');
    const recordRoom = remaining(limits.records, retainedRecords + reservedRecords);
    const byteRoom = remaining(limits.bytes, retainedBytes + reservedBytes);
    const queueRoom = remaining(limits.operations, queuedOperations);
    // The standalone audit-capacity-v1 profile derives this exact queue bound.
    const queueByteLimit = limits.operations * 4096n < RECORD_BYTES ? RECORD_BYTES : limits.operations * 4096n;
    const queueByteRoom = remaining(queueByteLimit, queuedBytes);
    requireValue(metadataMaximum !== 0n || metadataCharged === 0n, 'audit-snapshot-limit-mismatch');
    const metadataRoom = metadataMaximum === 0n ? null : remaining(metadataMaximum, metadataCharged);
    // Evidence renewal plus GET and HEAD, each with attempt and outcome.
    const criticalRecords = 2n * (1n + 2n * limits.routePairs);
    const budgetRecords = criticalRecords + limits.diagnostics + 2n * limits.competitors;
    const budgetBytes = budgetRecords * RECORD_BYTES;
    const reasons = [];
    if (closed) reasons.push('audit-closed');
    if (recovery) reasons.push('audit-recovery-pending');
    if (pending) reasons.push('audit-critical-pending');
    if (recordRoom < budgetRecords) reasons.push('audit-record-headroom-insufficient');
    if (byteRoom < budgetBytes) reasons.push('audit-byte-headroom-insufficient');
    if (queueRoom < 1n) reasons.push('audit-queue-operation-pressure');
    if (queueByteRoom < RECORD_BYTES) reasons.push('audit-queue-byte-pressure');
    if (metadataRoom === 0n) reasons.push('audit-metadata-pressure');
    const pressure = (charged, limit) => limit > 0n && charged * 100n >= limit * limits.warningPercent;
    const warnings = [];
    if (pressure(retainedRecords + reservedRecords, limits.records)) warnings.push('audit-record-warning');
    if (pressure(retainedBytes + reservedBytes, limits.bytes)) warnings.push('audit-byte-warning');
    if (pressure(metadataCharged, metadataMaximum)) warnings.push('audit-metadata-warning');
    if (metadataRoom === null) warnings.push('audit-metadata-unobserved');
    const recordCycles = recordRoom / budgetRecords, byteCycles = byteRoom / budgetBytes;
    const cycles = recordCycles < byteCycles ? recordCycles : byteCycles;
    return {...common(), status: reasons.length ? 'blocked' : warnings.length ? 'warning' : 'headroom-observed',
      reasons, warnings, nextAction: reasons.length ? 'inspect-audit-owner-before-explicit-continuation'
        : warnings.length ? 'plan-audit-maintenance-before-exhaustion' : 'recheck-live-admission-before-each-mutation',
      headroom: {records: String(recordRoom), bytes: String(byteRoom),
        queuedOperations: String(queueRoom), queuedBytes: String(queueByteRoom),
        metadataBytes: metadataRoom === null ? null : String(metadataRoom)},
      charged: {retainedRecords: String(retainedRecords), retainedBytes: String(retainedBytes),
        reservedRecords: String(reservedRecords), reservedBytes: String(reservedBytes)},
      budget: {criticalRecords: String(criticalRecords), diagnosticRecords: String(limits.diagnostics),
        competingCriticalOperations: String(limits.competitors), records: String(budgetRecords),
        bytes: String(budgetBytes), maximumRecordBytes: String(RECORD_BYTES)},
      planning: {cyclesAtBudget: String(cycles), minutesAtBudget: String(cycles * limits.cadence),
        cadenceMinutes: String(limits.cadence), competingTrafficBoundedByThisPlan: false},
      coverage: {unknownOutcomes: String(unknown), droppedObservations: String(dropped),
        unavailableEvents: String(storageUnavailable), previousSessionLossUnknown: previousLoss === 1n}};
  } catch (error) { return unavailable(error); }
}

export function inventoryHeadroom(envelope, expectedNode, options = {}) {
  // Validate caller options even when the remote observation is unavailable.
  settings({mode: 'durable'}, options);
  try {
    requireValue(envelope?.schemaVersion === 'latent.cli.result.v1' && envelope.category === 'success'
      && envelope.outcomeKnown === true, 'audit-snapshot-unavailable');
    const inventory = envelope.data?.inventory;
    requireValue(typeof expectedNode === 'string' && expectedNode.length >= 1 && expectedNode.length <= 128
      && inventory?.node?.id === expectedNode, 'audit-snapshot-node-mismatch');
    unsigned(inventory.observedAtUnixMillis);
    const topology = inventory.topology;
    requireValue(topology?.available === true && topology.complete === true && Array.isArray(topology.entries)
      && topology.entries.length <= 64, 'audit-snapshot-unavailable');
    const rows = topology.entries.filter(row => row?.name === 'audit-journal');
    requireValue(rows.length === 1, 'audit-snapshot-unavailable');
    const row = rows[0], attributes = row.attributes;
    requireValue(row.kind === 'store' && row.ownership === 'node-fixed' && attributes
      && typeof attributes === 'object' && !Array.isArray(attributes) && Object.keys(attributes).length <= 32
      && attributes.profile === 'audit-capacity-v1', 'audit-snapshot-invalid');
    requireValue(attributes.measurementStatus !== 'not-configured', 'audit-owner-not-configured');
    requireValue(row.configuredCount === '1' && attributes.measurementStatus === 'available', 'audit-snapshot-unavailable');
    const limit = (name, minimum, maximum) => {
      const value = unsigned(attributes[name]);
      requireValue(value >= BigInt(minimum) && value <= BigInt(maximum), 'audit-snapshot-limit-mismatch');
      return Number(value);
    };
    const audit = {mode: 'durable', records: limit('maximumRecords', 2, 16384),
      diskBytes: limit('maximumDiskBytes', 32768, 268435456),
      queuedOperations: limit('maximumQueuedOperations', 1, 256), queryOwners: limit('maximumQueryOwners', 1, 16)};
    requireValue(unsigned(attributes.maximumRecordBytes) === RECORD_BYTES
      && unsigned(attributes.maximumQueuedBytes) === BigInt(Math.max(16384, audit.queuedOperations * 4096)),
    'audit-snapshot-limit-mismatch');
    const counters = Object.fromEntries(Object.entries(attributes).filter(([key]) => key.startsWith('audit_')));
    return {...auditHeadroom({scope: 'node', counters, unavailable: []}, audit, options),
      node: expectedNode, observedAtUnixMillis: inventory.observedAtUnixMillis, sampleSource: 'node-inventory'};
  } catch (error) { return unavailable(error); }
}

export function humanHeadroom(report) {
  const lines = [`Audit headroom: ${report.status}. Advisory only; no capacity has been reserved.`];
  if (report.headroom) {
    lines.push(`Records available after reservations: ${report.headroom.records}; bytes: ${report.headroom.bytes}.`);
    lines.push(`Renewal critical lower bound: ${report.budget.criticalRecords} records; planning allowance: ${report.budget.records} records / ${report.budget.bytes} bytes.`);
    lines.push(`Capacity arithmetic: ${report.planning.cyclesAtBudget} cycles at ${report.planning.cadenceMinutes}-minute cadence; not a lifetime guarantee.`);
  }
  if (report.reasons.length) lines.push('Reasons: ' + report.reasons.join(', ') + '.');
  if (report.warnings.length) lines.push('Warnings: ' + report.warnings.join(', ') + '.');
  lines.push(`Next step: ${report.nextAction}.`);
  lines.push('Snapshot freshness and filesystem capacity are not established. Missing audit history never proves nonexecution.');
  return lines.join('\n');
}
