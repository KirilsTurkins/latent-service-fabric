import { isDeepStrictEqual } from "node:util";
import * as model from "../transactions.js";
import * as profile from "../management.js";
import type { ObservedOutcome, RecoveryIdentity } from "../transaction-client.js";
import type { Operation } from "./protocol/schema.js";
import { ShapeError } from "./protocol/preflight.js";
import { validateResponse as validateInvocation } from "./validation.js";

type RecordValue = Record<string, unknown>;
const controls = /[\p{Cc}]/u;
const maxU64 = 18446744073709551615n;
const platformCodes = new Set(["unavailable", "deadline-exceeded", "cancelled", "resource-exhausted",
  "permission-denied", "unauthenticated", "invalid-argument", "not-found", "already-exists",
  "incompatible-contract", "state-conflict", "dependency-failed", "guest-trap", "corrupt-artifact",
  "route-unavailable", "admission-rejected", "internal"]);

function object(value: unknown): RecordValue {
  if (!value || typeof value !== "object" || Array.isArray(value)
    || ![Object.prototype, null].includes(Object.getPrototypeOf(value))) throw new ShapeError();
  const descriptors = Object.getOwnPropertyDescriptors(value);
  if (Object.values(descriptors).some((item) => !("value" in item))) throw new ShapeError();
  return value as RecordValue;
}
function text(value: unknown, maximum = 256, required = true): asserts value is string {
  if (typeof value !== "string" || Buffer.byteLength(value) > maximum
    || (required && (value.length === 0 || controls.test(value)))) throw new ShapeError();
}
function id(value: unknown): asserts value is string { text(value); }
function identityValue(value: unknown): asserts value is string {
  text(value, 256, false);
  if (value.length === 0 || value.includes("\0")) throw new ShapeError();
}
function bytes(value: unknown, maximum = 256, required = true): asserts value is Uint8Array {
  if (!(value instanceof Uint8Array) || value.length > maximum || (required && value.length === 0)) throw new ShapeError();
}
function integer(value: unknown, maximum: bigint, positive = false): asserts value is bigint {
  if (typeof value !== "bigint" || value < (positive ? 1n : 0n) || value > maximum) throw new ShapeError();
}
function enumeration(value: unknown, maximum: number, field: string): void {
  if (typeof value !== "number" || !Number.isInteger(value) || value < 1 || value > maximum)
    throw new ShapeError(field, String(value));
}
function digest(value: unknown): void { if (typeof value !== "string" || !/^sha256:[0-9a-f]{64}$/.test(value)) throw new ShapeError(); }
function array(value: unknown, maximum = 128): unknown[] {
  if (!Array.isArray(value) || value.length > maximum) throw new ShapeError();
  for (let index = 0; index < value.length; index++) if (!Object.hasOwn(value, index)) throw new ShapeError();
  return value;
}
function same(left: unknown, right: unknown): void { if (!isDeepStrictEqual(left, right)) throw new ShapeError(); }
function namespace(raw: unknown, tenant: string): RecordValue {
  const value = object(raw);
  id(value.tenant); id(value.namespace); text(value.incarnation, 20);
  if (value.tenant !== tenant || !/^[1-9][0-9]{0,19}$/.test(value.incarnation)
    || BigInt(value.incarnation) > maxU64) throw new ShapeError();
  return value;
}
function publication(raw: unknown, tenant: string): void {
  const value = object(raw);
  if (value.tenant !== tenant || typeof value.id !== "string" || !/^publication:sha256:[0-9a-f]{64}$/.test(value.id)) throw new ShapeError();
}
function selected(raw: unknown): void { same(object(raw), model.currentProfile()); }
function commandSelector(raw: unknown, tenant: string): RecordValue {
  const value = object(raw);
  namespace(value.namespace, tenant); identityValue(value.operation); identityValue(value.clientKey);
  for (const key of ["entity", "sharedRecoveryScope"]) if (value[key] !== undefined) identityValue(value[key]);
  return value;
}
function inspect(raw: unknown, tenant: string): RecordValue {
  const value = object(raw); selected(value.profile); namespace(value.namespace, tenant);
  publication(value.authorizationPublication, tenant); return value;
}
function lookup(raw: unknown, tenant: string): RecordValue {
  const value = object(raw); selected(value.profile); commandSelector(value.command, tenant);
  publication(value.authorizationPublication, tenant);
  if (value.attemptId !== undefined) id(value.attemptId);
  return value;
}
function fence(raw: unknown): void {
  const value = object(raw);
  for (const key of ["commandId", "attemptId", "transactionId"]) id(value[key]);
  bytes(value.ownerFence);
}
function page(raw: unknown): RecordValue {
  const value = object(raw);
  if (typeof value.limit !== "number" || !Number.isInteger(value.limit) || value.limit < 1 || value.limit > 128) throw new ShapeError();
  if (value.cursor !== undefined) bytes(value.cursor);
  return value;
}
function media(value: unknown): void { text(value, 128); if (!/^[\x20-\x7e]+$/.test(value)) throw new ShapeError(); }
function metadata(raw: unknown, caller = false): void {
  const entries = Object.entries(object(raw));
  if (entries.length > 32) throw new ShapeError();
  let total = 0;
  for (const [key, value] of entries) {
    id(key); text(value, 1024, false);
    if (controls.test(value) || (caller && /^latent\.(auth|principal)\./i.test(key))) throw new ShapeError();
    total += Buffer.byteLength(key) + Buffer.byteLength(value);
  }
  if (total > 8192) throw new ShapeError();
}
function invocation(raw: unknown, tenant: string): void {
  const value = object(raw), target = object(value.target);
  for (const key of ["activationId", "parentActivationId", "rootActivationId", "idempotencyKey"]) if (value[key] !== undefined) id(value[key]);
  if (value.parentActivationId !== undefined && value.rootActivationId === undefined) throw new ShapeError();
  for (const key of ["tenant", "service", "contract", "function"]) id(target[key]);
  if (target.route !== undefined) id(target.route);
  if (target.tenant !== tenant) throw new ShapeError();
  bytes(value.payload, 1024 * 1024, false); media(value.mediaType); metadata(value.metadata, true); object(value.budget);
  if (typeof value.priority !== "number" || value.priority < 0 || value.priority > 255) throw new ShapeError();
}
function quota(raw: unknown): void {
  const value = object(raw);
  for (const key of ["stateKeys", "resultRows", "effectRows"]) integer(value[key], 1000000n, true);
  for (const key of ["stateBytes", "resultBytes", "effectBytes", "payloadBytes", "recoveryBytes"]) integer(value[key], 1073741824n, true);
  if ((value.recoveryBytes as bigint) > (value.resultBytes as bigint)) throw new ShapeError();
}

function dispatcherGeneration(raw: unknown): RecordValue {
  const value = object(raw); integer(value.ownerEpoch, maxU64, true); integer(value.revision, maxU64, true); return value;
}
function dispatcherControl(raw: unknown): RecordValue {
  const value = object(raw); selected(value.profile); enumeration(value.scope, 1, "dispatcher.scope");
  id(value.operationId); enumeration(value.action, 2, "dispatcher.action");
  if (dispatcherGeneration(value.expectedGeneration).revision === maxU64) throw new ShapeError();
  return value;
}
function dispatcherReceipt(raw: unknown, original: RecordValue): void {
  const value = object(raw); for (const key of ["operationId", "receiptId", "authenticatedOperator", "actorTenant"]) id(value[key]);
  enumeration(value.action, 2, "dispatcher.action"); enumeration(value.disposition, 5, "dispatcher.disposition");
  const before = dispatcherGeneration(value.beforeGeneration), after = dispatcherGeneration(value.afterGeneration);
  same(value.operationId, original.operationId); same(value.action, original.action); same(before, original.expectedGeneration);
  same(after.ownerEpoch, before.ownerEpoch); same(after.revision, (before.revision as bigint) + 1n);
  if (value.disposition !== 1 || (value.action === 2 && (value.clockContinuityProven !== true || value.restoreReviewRequired !== false))) throw new ShapeError();
}
export function validateRequest(operation: Operation, raw: unknown, tenant: string): void {
  const value = object(raw);
  switch (operation) {
    case "invokeCommand": {
      selected(value.profile); commandSelector(value.command, tenant); invocation(value.invocation, tenant); identityValue(value.inputFormat);
      const keys = new Set<string>();
      for (const raw of array(value.expectedVersions)) {
        const expected = object(raw); bytes(expected.key, 1024, false);
        const key = Buffer.from(expected.key).toString("hex");
        if (keys.has(key)) throw new ShapeError(); keys.add(key);
        if ((expected.absent !== undefined) === (expected.version !== undefined)) throw new ShapeError();
        if (expected.absent !== undefined && expected.absent !== true) throw new ShapeError();
        if (expected.version !== undefined) bytes(expected.version);
      }
      if (value.retryAttempt !== undefined) { const retry = object(value.retryAttempt); id(retry.requestId); fence(retry.expectedAbort); }
      break;
    }
    case "query":
      selected(value.profile); namespace(value.namespace, tenant); invocation(value.invocation, tenant);
      if (value.entity !== undefined) identityValue(value.entity);
      if (value.minimumViewVersion !== undefined) bytes(value.minimumViewVersion);
      break;
    case "lookupCommand": lookup(value, tenant); break;
    case "lookupCommit": lookup(value, tenant); id(value.receiptId); break;
    case "getEffect": lookup(value, tenant); id(value.effectId); break;
    case "listEffectHistory": lookup(value.effect, tenant); id(object(value.effect).effectId); page(value.page); break;
    case "cancelCommand": lookup(value.command, tenant); text(value.reason, 1024); break;
    case "inspectNamespace": inspect(value, tenant); break;
    case "selectEntity": inspect(value.namespace, tenant); page(value.page); if (value.prefix !== undefined) bytes(value.prefix, 256, false); break;
    case "getStateOperationReceipt": inspect(value.namespace, tenant); id(value.operationId); break;
    case "mutateState":
      inspect(value.namespace, tenant); id(value.operationId); bytes(value.expectedVersion); digest(value.expectedPolicyDigest); text(value.reason, 1024);
      enumeration(value.mutation, 4, "state.mutation");
      if (value.recordId !== undefined) id(value.recordId);
      if ((value.mutation === 4) !== (value.recordId === undefined)) throw new ShapeError();
      break;
    case "mutateNamespace": {
      const target = inspect(value.namespace, tenant);
      id(value.operationId); integer(value.expectedGeneration, maxU64); enumeration(value.mutation, 5, "namespace.mutation");
      if ((value.mutation === 1) !== (value.expectedGeneration === 0n)
        || (value.mutation === 1 && object(target.namespace).incarnation !== "1")) throw new ShapeError();
      if (value.mutation === 1 || value.mutation === 5) { const config = object(value.configuration); id(config.stateSchema); quota(config.quota); }
      else if (value.configuration !== undefined) throw new ShapeError();
      break;
    }
    case "inspectDispatcher": selected(value.profile); enumeration(value.scope, 1, "dispatcher.scope"); break;
    case "controlDispatcher": dispatcherControl(value); break;
    case "getDispatcherOperation": dispatcherControl(value.original); break;
    default: throw new ShapeError();
  }
}

function source(raw: unknown): RecordValue {
  const value = object(raw);
  if (typeof value.publicationId !== "string" || !/^publication:sha256:[0-9a-f]{64}$/.test(value.publicationId)) throw new ShapeError();
  for (const key of ["revisionId", "inputFormat", "resultFormat"]) identityValue(value[key]);
  for (const key of ["releaseDigest", "componentDigest", "contractDigest", "stateSchema"]) digest(value[key]);
  integer(value.routeGeneration, maxU64, true); return value;
}
function retention(raw: unknown): void {
  const value = object(raw); id(value.recordFormat);
  if (typeof value.recordVersion !== "number" || value.recordVersion < 1) throw new ShapeError();
  for (const key of array(value.requiredRecordIds, 256)) id(key);
}
function resultBody(raw: unknown, kind: "success" | "businessRejection" | "technicalFailure"): void {
  const value = object(raw);
  if (kind === "technicalFailure") {
    id(value.code); text(value.message, 1024, false);
    if (!platformCodes.has(value.code)) throw new ShapeError("platform_error.code", value.code);
    for (const raw of array(value.detailItems, 16)) { const detail = object(raw); id(detail.kind); metadata(detail.fields); }
    return;
  }
  bytes(value.payload, 1024 * 1024, false); media(value.mediaType); metadata(value.metadata);
  if (kind === "businessRejection") { id(value.code); text(value.message, 4096, false); }
  else { if (value.committedStateVersion !== undefined) id(value.committedStateVersion); for (const idValue of array(value.effectIds)) id(idValue); }
}
function command(raw: unknown, selector: unknown, tenant: string): RecordValue {
  const value = object(raw), key = object(value.key), requested = object(selector);
  namespace(key.namespace, tenant); identityValue(key.recoveryScope); identityValue(key.operation); identityValue(key.clientKey);
  if (key.entity !== undefined) identityValue(key.entity);
  for (const part of ["namespace", "operation", "entity", "clientKey"]) same(key[part], requested[part]);
  enumeration(value.outcome, 7, "command.outcome");
  const known = value.outcome !== 5 && value.outcome !== 6;
  if (known || value.commandId !== "") id(value.commandId);
  if (known || value.attemptId !== "") id(value.attemptId);
  bytes(value.fingerprintSha256, 32, known);
  if (known && value.fingerprintSha256.length !== 32) throw new ShapeError();
  if (known || value.source !== undefined) source(value.source);
  if (value.retention !== undefined) retention(value.retention);
  const results = (["success", "businessRejection", "technicalFailure"] as const).filter((key) => value[key] !== undefined);
  if (results.length > 1) throw new ShapeError();
  for (const key of results) resultBody(value[key], key);
  if (value.cleanupFailure !== undefined) resultBody(value.cleanupFailure, "technicalFailure");
  if (value.commit !== undefined) {
    const commit = object(value.commit);
    for (const key of ["commandId", "attemptId", "transactionId", "receiptId"]) id(commit[key]);
    bytes(commit.committedVersion); source(commit.source);
    const ids = array(commit.effectIds); for (const item of ids) id(item);
    if (new Set(ids).size !== ids.length) throw new ShapeError();
    for (const key of ["commandId", "attemptId", "source"]) same(commit[key], value[key]);
  }
  if (value.provenAbort !== undefined) {
    fence(value.provenAbort);
    for (const key of ["commandId", "attemptId"]) same(object(value.provenAbort)[key], value[key]);
  }
  const omitted = results.length === 0 && value.retention !== undefined && object(value.retention).payloadAvailable === false;
  const committed = value.applicationStateCommitted === true, durable = value.metadataDurable === true;
  switch (value.outcome) {
    case 2: if (!durable || !committed || value.commit === undefined || value.provenAbort !== undefined || !(value.success !== undefined || omitted)) throw new ShapeError(); break;
    case 3: if (!durable || committed || value.commit !== undefined || value.provenAbort !== undefined || !(value.businessRejection !== undefined || omitted)) throw new ShapeError(); break;
    case 4: if (!durable || committed || value.commit !== undefined || value.provenAbort === undefined || value.success !== undefined || value.businessRejection !== undefined) throw new ShapeError(); break;
    case 7: if (!durable || value.provenAbort !== undefined || results.length !== 0 || committed !== (value.commit !== undefined)) throw new ShapeError(); break;
    default: if (committed || value.commit !== undefined || value.provenAbort !== undefined || results.length !== 0) throw new ShapeError();
  }
  return value;
}
function effect(raw: unknown, expectedId: unknown): void {
  const value = object(raw);
  for (const key of ["effectId", "commandId", "commandAttemptId", "providerProfile"]) id(value[key]);
  for (const key of ["providerReceipt", "failureCode", "managementOperationReceiptId"]) if (value[key] !== undefined) id(value[key]);
  enumeration(value.disposition, 8, "effect.disposition"); same(value.effectId, expectedId);
  if (value.retention !== undefined) retention(value.retention);
}
function boundedPage(raw: unknown, request: unknown, count: number): void {
  const value = object(raw), requested = object(request);
  if (value.returnedCount !== count || count > (requested.limit as number)) throw new ShapeError();
  integer(value.encodedBytes, 1048576n);
  if (value.nextCursor !== undefined) { bytes(value.nextCursor); if (isDeepStrictEqual(value.nextCursor, requested.cursor)) throw new ShapeError(); }
}
function receipt(raw: unknown, original: RecordValue, tenant: string, namespaceReceipt: boolean): RecordValue {
  const value = object(raw), target = object(object(original.namespace).namespace);
  namespace(value.namespace, tenant);
  for (const key of ["operationId", "receiptId", "authenticatedOperator"]) id(value[key]);
  same(value.operationId, original.operationId); enumeration(value.disposition, 5, "state.disposition");
  if (namespaceReceipt) {
    const actual = object(value.namespace); same(actual.tenant, target.tenant); same(actual.namespace, target.namespace);
    id(value.stateSchema); enumeration(value.status, 4, "namespace.status"); enumeration(value.mutation, 5, "namespace.mutation");
    if (value.disposition === 1) integer(value.afterGeneration, maxU64, true);
  } else {
    same(value.namespace, target); bytes(value.beforeVersion); bytes(value.afterVersion); digest(value.policyDigest); enumeration(value.mutation, 4, "state.mutation");
    if (value.recordId !== undefined) id(value.recordId);
  }
  return value;
}
function view(raw: unknown, expected: unknown, tenant: string): void {
  const value = object(raw); namespace(value.namespace, tenant); same(value.namespace, expected); bytes(value.version); id(value.stateSchema);
}
function linkedInvocation(raw: unknown, captured: unknown, tenant: string, original: unknown): void {
  const value = object(raw), selected = source(captured);
  validateInvocation("invoke", original, value, tenant);
  same(value.publicationId, selected.publicationId); same(value.revisionId, selected.revisionId);
  same(value.releaseDigest, selected.componentDigest); same(value.routeGeneration, selected.routeGeneration);
  for (const kind of ["success", "declaredError", "platformFailure"] as const)
    if (value[kind] !== undefined) resultBody(value[kind], kind === "declaredError" ? "businessRejection" : kind === "platformFailure" ? "technicalFailure" : kind);
}

export function validateResponse(operation: Operation, original: unknown, value: RecordValue, tenant: string): void {
  const requested = object(original);
  switch (operation) {
    case "invokeCommand": {
      const inspected = command(value.command, requested.command, tenant);
      linkedInvocation(value.invocation, inspected.source, tenant, requested.invocation ?? {});
      const invoked = object(value.invocation);
      for (const [left, right] of [["success", "success"], ["businessRejection", "declaredError"], ["technicalFailure", "platformFailure"]])
        if (inspected[left!] !== undefined) same(inspected[left!], invoked[right!]);
      if (inspected.success === undefined && inspected.businessRejection === undefined && inspected.technicalFailure === undefined && invoked.platformFailure === undefined) throw new ShapeError();
      break;
    }
    case "lookupCommand": { const inspected = command(value.command, requested.command, tenant); if (requested.attemptId !== undefined) same(inspected.attemptId, requested.attemptId); break; }
    case "lookupCommit": { const inspected = command(value.command, requested.command, tenant); same(object(inspected.commit).receiptId, requested.receiptId); break; }
    case "getEffect": effect(value.effect, requested.effectId); break;
    case "listEffectHistory": { const records = array(value.receipts); for (const item of records) effect(item, object(requested.effect).effectId); boundedPage(value.page, requested.page, records.length); break; }
    case "cancelCommand":
      enumeration(value.disposition, 5, "command.cancel.disposition");
      if (value.command !== undefined) { const inspected = command(value.command, object(requested.command).command, tenant); if (value.disposition === 2 && inspected.outcome !== 2) throw new ShapeError(); }
      else if (value.disposition !== 4) throw new ShapeError();
      break;
    case "query": view(value.view, requested.namespace, tenant); linkedInvocation(value.invocation, value.source, tenant, requested.invocation ?? {}); break;
    case "inspectNamespace": {
      const inspected = object(value.namespace); view(inspected.view, requested.namespace, tenant); enumeration(inspected.status, 4, "namespace.status");
      integer(inspected.generation, maxU64, true); quota(inspected.quota); id(inspected.engineProfile); digest(inspected.engineProfileDigest);
      for (const format of array(inspected.retainedFormats)) retention(format);
      break;
    }
    case "selectEntity": {
      const entries = array(value.entities), names = new Set<string>();
      for (const item of entries) { const entry = object(item); identityValue(entry.entity); bytes(entry.version); if (names.has(entry.entity)) throw new ShapeError(); names.add(entry.entity); }
      boundedPage(value.page, requested.page, entries.length); break;
    }
    case "mutateState": {
      const accepted = receipt(value.receipt, requested, tenant, false);
      for (const [result, expected] of [["mutation", "mutation"], ["recordId", "recordId"], ["beforeVersion", "expectedVersion"], ["policyDigest", "expectedPolicyDigest"]]) same(accepted[result!], requested[expected!]);
      break;
    }
    case "mutateNamespace": {
      const accepted = receipt(value.receipt, requested, tenant, true); same(accepted.mutation, requested.mutation);
      same(accepted.beforeGeneration, requested.mutation === 1 ? undefined : requested.expectedGeneration);
      if (accepted.disposition === 1) {
        const expected = requested.expectedGeneration as bigint, target = object(object(requested.namespace).namespace);
        const incarnation = BigInt(target.incarnation as string) + (requested.mutation === 5 ? 1n : 0n);
        if (expected === maxU64 || incarnation > maxU64) throw new ShapeError();
        same(accepted.afterGeneration, expected + 1n); same(object(accepted.namespace).incarnation, String(incarnation));
        same(accepted.status, requested.mutation === 1 || requested.mutation === 5 ? 1 : requested.mutation);
        if (requested.configuration !== undefined) same(accepted.stateSchema, object(requested.configuration).stateSchema);
      }
      break;
    }
    case "getStateOperationReceipt":
      if ((value.receipt !== undefined) === (value.namespaceReceipt !== undefined)) throw new ShapeError();
      receipt(value.receipt ?? value.namespaceReceipt, requested, tenant, value.namespaceReceipt !== undefined); break;
    case "inspectDispatcher": {
      const snapshot = object(value.dispatcher); dispatcherGeneration(snapshot.generation); enumeration(snapshot.failure, 7, "dispatcher.failure");
      if ((snapshot.pendingControl === true || snapshot.restoreReviewRequired === true) && snapshot.paused !== true) throw new ShapeError();
      break;
    }
    case "controlDispatcher":
      dispatcherReceipt(value.receipt, requested);
      if ((value.replayed === true && value.published === true) || (requested.action === 1 && value.published === true && value.paused !== true)) throw new ShapeError();
      break;
    case "getDispatcherOperation": dispatcherReceipt(value.receipt, object(requested.original)); break;
    default: throw new ShapeError();
  }
}

export function validateIndependentAudit(value: RecordValue): void {
  if (value.auditAck !== undefined) enumeration(object(value.auditAck).status, 4, "audit.status");
}

/** Snapshot only bounded recovery data, without retaining application input. */
export function identity(operation: Operation, raw: unknown): RecoveryIdentity {
  try {
    const value = object(raw), result: RecordValue = {};
    const assign = (key: string, source: unknown) => { if (source !== undefined) result[key] = structuredClone(source); };
    const invocationValue = value.invocation === undefined ? {} : object(value.invocation);
    if (invocationValue.activationId !== undefined) { id(invocationValue.activationId); assign("activationId", invocationValue.activationId); }
    let inspected: RecordValue | undefined, selectedCommand: RecordValue | undefined;
    if (["inspectNamespace", "selectEntity", "mutateNamespace", "mutateState", "getStateOperationReceipt"].includes(operation))
      inspected = operation === "inspectNamespace" ? value : object(value.namespace);
    if (["invokeCommand", "lookupCommand", "lookupCommit", "getEffect"].includes(operation)) selectedCommand = object(value.command);
    if (operation === "listEffectHistory") selectedCommand = object(object(value.effect).command);
    if (operation === "cancelCommand") selectedCommand = object(object(value.command).command);
    const namespaceValue = inspected?.namespace ?? selectedCommand?.namespace ?? (operation === "query" ? value.namespace : undefined);
    if (namespaceValue !== undefined) { const selected = object(namespaceValue); namespace(selected, selected.tenant as string); assign("namespace", selected); }
    if (selectedCommand !== undefined) { commandSelector(selectedCommand, object(selectedCommand.namespace).tenant as string); assign("command", selectedCommand); }
    for (const key of ["operationId", "attemptId", "receiptId", "effectId"]) if (value[key] !== undefined) { id(value[key]); assign(key, value[key]); }
    if (operation === "listEffectHistory") assign("effectId", object(value.effect).effectId);
    const current = operation === "cancelCommand" ? object(value.command) : operation === "listEffectHistory" ? object(value.effect) : inspected ?? value;
    if (current.authorizationPublication !== undefined) { publication(current.authorizationPublication, object(current.authorizationPublication).tenant as string); assign("authorizationPublication", current.authorizationPublication); }
    if (operation === "mutateNamespace" && value.expectedGeneration !== undefined) { integer(value.expectedGeneration, maxU64); assign("expectedGeneration", value.expectedGeneration); }
    if (value.expectedVersion !== undefined) { bytes(value.expectedVersion); assign("expectedVersion", value.expectedVersion); }
    if (value.expectedPolicyDigest !== undefined) { digest(value.expectedPolicyDigest); assign("expectedPolicyDigest", value.expectedPolicyDigest); }
    if (operation === "invokeCommand") {
      const entries = array(value.expectedVersions);
      for (const entry of entries) { const item = object(entry); bytes(item.key, 1024, false); if (item.version !== undefined) bytes(item.version); }
      assign("expectedVersions", entries);
      if (value.retryAttempt !== undefined) { const retry = object(value.retryAttempt); id(retry.requestId); fence(retry.expectedAbort); assign("retryRequestId", retry.requestId); assign("expectedAbort", retry.expectedAbort); assign("attemptId", object(retry.expectedAbort).attemptId); }
    }
    if (operation === "controlDispatcher" || operation === "getDispatcherOperation") {
      const original = operation === "controlDispatcher" ? value : object(value.original);
      id(original.operationId); enumeration(original.action, 2, "dispatcher.action"); dispatcherGeneration(original.expectedGeneration);
      assign("operationId", original.operationId); assign("dispatcherAction", original.action); assign("dispatcherExpectedGeneration", original.expectedGeneration);
    }
    return result as RecoveryIdentity;
  } catch { return {}; }
}

export function context(operation: Operation, raw: RecordValue): RecordValue {
  const invocationIdentity = raw.invocation === undefined ? {} : { invocation: { activationId: object(raw.invocation).activationId } };
  if (operation === "invokeCommand") return { command: raw.command, ...invocationIdentity };
  if (operation === "query") return { namespace: raw.namespace, ...invocationIdentity };
  return raw;
}

export function observe(operation: Operation, value: RecordValue): ObservedOutcome | undefined {
  if (["invokeCommand", "lookupCommand", "lookupCommit", "cancelCommand"].includes(operation) && value.command !== undefined) {
    const { success: _success, businessRejection: _rejection, technicalFailure: _technical, cleanupFailure: _cleanup, ...rest } = object(value.command);
    return { kind: "command", command: rest as unknown as model.CommandInspection };
  }
  if (operation === "getEffect") return { kind: "effect", receipt: value.effect as model.EffectReceipt };
  if (operation === "mutateNamespace" || value.namespaceReceipt !== undefined) return { kind: "namespace", receipt: (value.receipt ?? value.namespaceReceipt) as model.NamespaceOperationReceipt };
  if (operation === "mutateState" || operation === "getStateOperationReceipt") return { kind: "state", receipt: value.receipt as model.StateOperationReceipt };
  if (operation === "controlDispatcher" || operation === "getDispatcherOperation") return { kind: "dispatcher", receipt: value.receipt as model.DispatcherOperationReceipt };
  return undefined;
}

export function known(value: ObservedOutcome | undefined): boolean {
  if (!value || value.kind === "effect") return false;
  if (value.kind === "command") return value.command.metadataDurable && [2, 3, 4].includes(value.command.outcome);
  if (value.kind === "dispatcher") return value.receipt.disposition === 1;
  return [1, 2, 3].includes(value.receipt.disposition);
}

export function extendIdentity(original: RecoveryIdentity, observed: ObservedOutcome | undefined): RecoveryIdentity {
  if (!observed || observed.kind === "effect") return original;
  if (observed.kind !== "command") return { ...original, receiptId: observed.receipt.receiptId };
  const value = observed.command;
  return { ...original,
    ...(value.commandId ? { commandId: value.commandId } : {}),
    ...(original.attemptId === undefined && value.attemptId ? { attemptId: value.attemptId } : {}),
    ...(value.fingerprintSha256.length ? { fingerprintSha256: value.fingerprintSha256 } : {}),
    ...(original.receiptId === undefined && value.commit ? { receiptId: value.commit.receiptId } : {}),
  };
}
