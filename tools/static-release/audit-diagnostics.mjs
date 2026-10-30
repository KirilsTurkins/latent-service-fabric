// Diagnostic vocabulary only. Neither an audit error nor an acknowledgement
// establishes whether a dispatched catalog mutation committed.
const REASONS = new Set(['audit-capacity', 'audit-critical-pending', 'audit-busy',
  'audit-unavailable', 'audit-closed', 'audit-corrupt']);
const CODES = new Set(['unavailable', 'deadline-exceeded', 'cancelled', 'resource-exhausted',
  'permission-denied', 'unauthenticated', 'invalid-argument', 'not-found', 'already-exists',
  'incompatible-contract', 'state-conflict', 'dependency-failed', 'guest-trap', 'corrupt-artifact',
  'route-unavailable', 'admission-rejected', 'internal', 'unimplemented', 'request-rejected']);
// Successful protobuf-body projections and error metadata use separate closed
// spellings. Preserve the received spelling and the exact independent sequence.
const ACK_STATUSES = new Map([
  ['durable', true], ['outcome-unknown', true], ['audit-unavailable', false], ['disabled', false],
  ['AUDIT_ACK_STATUS_DURABLE', true], ['AUDIT_ACK_STATUS_OUTCOME_UNKNOWN', true],
  ['AUDIT_ACK_STATUS_AUDIT_UNAVAILABLE', false], ['AUDIT_ACK_STATUS_DISABLED', false],
]);
const U64 = 18446744073709551615n;

export function publicCode(value) { return CODES.has(value) ? value : 'request-rejected'; }
export function publicAuditReason(value) { return REASONS.has(value) ? value : null; }
export function auditReason(result) {
  const details = result?.error?.details;
  if (!Array.isArray(details) || details.length > 16) return null;
  let reason = null;
  for (const detail of details) {
    if (detail?.kind !== 'audit-journal') continue;
    const candidate = publicAuditReason(detail.fields?.reason);
    // Conflicting or unknown audit vocabulary is not a usable diagnosis.
    if (candidate === null || (reason !== null && reason !== candidate)) return null;
    reason = candidate;
  }
  return reason;
}
export function auditAck(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value)
    || !ACK_STATUSES.has(value.status)) return null;
  const sequence = value.attemptSequence ?? null;
  if (sequence !== null && (typeof sequence !== 'string' || !/^[1-9][0-9]{0,19}$/.test(sequence)
    || BigInt(sequence) > U64)) return null;
  if (ACK_STATUSES.get(value.status) && sequence === null) return null;
  return {status: value.status, attemptSequence: sequence};
}
export function rememberAudit(attempt, result) {
  const reason = auditReason(result), ack = auditAck(result?.data?.auditAck);
  if (reason !== null) attempt.auditReason = reason;
  if (ack !== null) attempt.auditAck = ack;
  // Do not erase independently retained facts when a later lookup omits them.
}
export function knownRejection(result) {
  if (result?.outcomeKnown !== true || result.category === 'success') return false;
  if (result?.data?.receipt != null) return false;
  if (Array.isArray(result?.error?.details) && result.error.details.some(
    detail => detail?.fields?.committed === 'true')) return false;
  return result.requestDispatched === false || ['platform-failure', 'declared-error', 'not-found'].includes(result.category);
}
export function recoveryAction(attempt) {
  if (attempt.status === 'pending') return 'recover-original-operation-no-replay';
  if (attempt.status !== 'rejected') return null;
  switch (publicAuditReason(attempt.auditReason)) {
    case 'audit-capacity': return 'restore-audit-headroom-then-explicit-new-plan';
    case 'audit-critical-pending': return 'reconcile-audit-pending-then-explicit-new-plan';
    case 'audit-busy': return 'inspect-audit-pressure-then-explicit-new-plan';
    case 'audit-unavailable':
    case 'audit-closed':
    case 'audit-corrupt': return 'recover-audit-owner-then-explicit-new-plan';
    default: return attempt.code === 'state-conflict' ? 'recheck-original-preconditions' : 'explicit-new-plan-required';
  }
}
export function operationSummary(attempt) {
  return {id: attempt.id, status: attempt.status,
    expectedGeneration: attempt.generation, expectedStateVersion: attempt.stateVersion,
    code: attempt.code === undefined ? null : publicCode(attempt.code),
    auditReason: publicAuditReason(attempt.auditReason), auditAck: auditAck(attempt.auditAck),
    nextAction: recoveryAction(attempt)};
}
