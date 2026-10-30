import test from 'node:test';
import assert from 'node:assert/strict';
import {auditAck, auditReason, knownRejection, operationSummary, publicCode, rememberAudit} from './audit-diagnostics.mjs';

test('acknowledgements preserve exact u64s and never retain arbitrary remote fields', () => {
  const value = {status: 'durable', attemptSequence: '18446744073709551615', credential: 'secret'};
  assert.deepEqual(auditAck(value), {status: 'durable', attemptSequence: '18446744073709551615'});
  for (const sequence of [0, '0', '01', '-1', '18446744073709551616', 9007199254740993, '', null]) {
    assert.equal(auditAck({status: 'durable', attemptSequence: sequence}), null);
  }
  assert.equal(auditAck({status: 'peer-secret', attemptSequence: '1'}), null);
  assert.deepEqual(auditAck({status: 'disabled'}), {status: 'disabled', attemptSequence: null});
});

test('omitted recovery metadata cannot erase original acknowledgement', () => {
  const attempt = {};
  rememberAudit(attempt, {data: {auditAck: {status: 'outcome-unknown', attemptSequence: '9'}}});
  rememberAudit(attempt, {data: {}});
  assert.deepEqual(attempt.auditAck, {status: 'outcome-unknown', attemptSequence: '9'});
});

test('bounded diagnostic vocabulary does not infer disposition from a reason', () => {
  const detail = {kind: 'audit-journal', fields: {reason: 'audit-capacity'}};
  assert.equal(auditReason({error: {details: Array(17).fill(detail)}}), null);
  assert.equal(auditReason({error: {details: [detail]}}), 'audit-capacity');
  assert.equal(auditReason({error: {message: 'audit-capacity'}}), null);
  assert.equal(publicCode('remote-secret'), 'request-rejected');
  const response = {category: 'platform-failure', requestDispatched: true,
    outcomeKnown: false, error: {code: 'resource-exhausted', details: [detail]}};
  assert.equal(knownRejection(response), false);
  assert.equal(knownRejection({...response, outcomeKnown: true}), true);
  assert.equal(knownRejection({...response, outcomeKnown: true,
    error: {details: [{kind: 'deployment-mutation', fields: {committed: 'true'}}]}}), false);
});

test('old journals need no invented audit acknowledgement', () => {
  const summary = operationSummary({id: 'route-original', generation: '1', stateVersion: '2',
    status: 'rejected', code: 'resource-exhausted'});
  assert.equal(summary.auditAck, null);
  assert.equal(summary.auditReason, null);
  assert.equal(summary.nextAction, 'explicit-new-plan-required');
});

test('successful protobuf and error-metadata audit acknowledgements preserve their original spellings', () => {
  for (const status of ['AUDIT_ACK_STATUS_DURABLE', 'AUDIT_ACK_STATUS_OUTCOME_UNKNOWN']) {
    assert.deepEqual(auditAck({status, attemptSequence: '9007199254740993'}), {status, attemptSequence: '9007199254740993'});
    assert.equal(auditAck({status}), null);
  }
  for (const status of ['AUDIT_ACK_STATUS_AUDIT_UNAVAILABLE', 'AUDIT_ACK_STATUS_DISABLED']) {
    assert.deepEqual(auditAck({status}), {status, attemptSequence: null});
  }
  for (const status of ['AUDIT_ACK_STATUS_UNSPECIFIED', 'future-status', 1, null]) {
    assert.equal(auditAck({status, attemptSequence: '1'}), null);
  }
});
