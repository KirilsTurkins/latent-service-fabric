// These are real HTTP/2 codec/transport checks. This peer is not a node engine.
import assert from "node:assert/strict";
import test from "node:test";
import { once } from "node:events";
import { createServer } from "node:http2";
import { create, fromBinary, toBinary } from "@bufbuild/protobuf";
import { RpcClient, RpcError } from "../../dist/node/index.js";
import { method } from "../../dist/node/protocol/schema.js";
import { encode, decode } from "../../dist/node/protocol/codec.js";
import { ShapeError } from "../../dist/node/protocol/preflight.js";
import { validateResponse } from "../../dist/node/transaction.js";
import { currentProfile, CommandOutcome } from "../../dist/transactions.js";
import { FailureCategory, OutcomeKnowledge } from "../../dist/management.js";

const digest = `sha256:${"1".repeat(64)}`;
const publication = { id: `publication:sha256:${"2".repeat(64)}`, tenant: "tests" };
const namespace = { tenant: "tests", namespace: "transactional-aggregate", incarnation: "1" };
const selector = { namespace, operation: "update", clientKey: "business-key" };
const current = currentProfile();
const source = { publicationId: publication.id, revisionId: "revision", releaseDigest: digest,
  routeGeneration: 18446744073709551615n, contractDigest: digest, stateSchema: digest,
  inputFormat: "input-v1", resultFormat: "result-v1", componentDigest: digest };
const inspect = { profile: current, namespace, authorizationPublication: publication };
const lookup = { profile: current, command: selector, authorizationPublication: publication };
const invoke = { target: { tenant: "tests", service: "aggregate", contract: "api@1.0.0", function: "update" },
  payload: Uint8Array.of(1), mediaType: "application/octet-stream", metadata: {}, budget: {}, priority: 0, activationId: "activation-original" };
const command = { profile: current, command: selector, invocation: invoke, inputFormat: "input-v1",
  expectedVersions: [{ key: Uint8Array.of(1), version: Uint8Array.of(2) }] };
const quota = { stateKeys: 1n, stateBytes: 1024n, resultRows: 1n, resultBytes: 1024n,
  effectRows: 1n, effectBytes: 1024n, payloadBytes: 1024n, recoveryBytes: 1024n };
const token = "LSF-PUBLIC-NODE-CLIENT-FIXTURE-ONLY";
const dispatcherControl = { profile: current, scope: 1, operationId: "dispatcher-original", action: 1,
  expectedGeneration: { ownerEpoch: 18446744073709551615n, revision: 18446744073709551614n } };
const effectMutation = { effect: { ...lookup, effectId: "a".repeat(64) }, operationId: "effect-original", mutation: 1,
  expectedVersion: new Uint8Array(32).fill(1), expectedPolicyDigest: digest, reason: "explicit redrive", retryDelayMillis: 100n };
function effectPlan(original = effectMutation) { return { original, planDigest: new Uint8Array(32).fill(2), managementSequence: 1,
  ownerEpoch: 18446744073709551615n, claimGeneration: 1n, dispatchAttempt: 1, preparedAtUnixMillis: 1000n, expiresAtUnixMillis: 2000n,
  before: 4, safety: 1 }; }
function effectReceipt(plan) { return { operationId: plan.original.operationId, receiptId: "effect-management-receipt", mutation: plan.original.mutation,
  namespace, authenticatedOperator: "operator", recordId: plan.original.effect.effectId, beforeVersion: plan.original.expectedVersion,
  afterVersion: new Uint8Array(32).fill(3), completedAtUnixMillis: 1500n, policyDigest: digest, disposition: 1,
  effect: { originalPlan: plan, before: plan.before, after: 9, fact: 1 } }; }
function dispatcherReceipt(original) { return { operationId: original.operationId, receiptId: "dispatcher-receipt", action: original.action,
  authenticatedOperator: "operator", actorTenant: "operator-tenant", beforeGeneration: original.expectedGeneration,
  afterGeneration: { ownerEpoch: original.expectedGeneration.ownerEpoch, revision: original.expectedGeneration.revision + 1n },
  disposition: 1, clockContinuityProven: true }; }

function inspected(committed = false) {
  const result = { key: { namespace, operation: "update", clientKey: "business-key", recoveryScope: "host-caller" },
    commandId: "command-id", attemptId: "attempt-id", fingerprintSha256: new Uint8Array(32).fill(3),
    outcome: committed ? 2 : 3, metadataDurable: true, applicationStateCommitted: committed, source };
  if (committed) {
    result.success = { payload: Uint8Array.of(4), mediaType: "application/octet-stream", metadata: {}, effectIds: ["effect-id"] };
    result.commit = { commandId: "command-id", attemptId: "attempt-id", transactionId: "transaction-id",
      committedVersion: Uint8Array.of(3), committedAtUnixMillis: 1n, effectIds: ["effect-id"], receiptId: "receipt-id", source };
  } else result.businessRejection = { code: "declined", message: "declined", payload: Uint8Array.of(9), mediaType: "application/octet-stream", metadata: {} };
  return result;
}
function invoked(result) { return { activationId: "activation-original", revisionId: source.revisionId,
  releaseDigest: source.componentDigest, routeGeneration: source.routeGeneration, publicationId: source.publicationId,
  consumption: {}, result }; }
function wireInspection(value) {
  const result = { ...value };
  for (const kind of ["success", "businessRejection", "technicalFailure"])
    if (value[kind] !== undefined) result.retainedResult = { case: kind, value: value[kind] };
  return result;
}
function stateReceipt(request) { return { operationId: request.operationId, receiptId: "state-receipt", mutation: 4,
  namespace, authenticatedOperator: "operator", beforeVersion: Uint8Array.of(1), afterVersion: Uint8Array.of(2),
  policyDigest: digest, disposition: 1 }; }

test("effect preparation is unknown and historical recovery preserves the original CAS with current read authority", async () => {
  const fixture = await peer();
  try {
    const prepared = await fixture.client.planEffectMutation(effectMutation);
    const plan = prepared.value.plan;
    assert.equal(prepared.metadata.outcome, OutcomeKnowledge.Unknown);
    assert.deepEqual(prepared.metadata.transactionIdentity.effectMutation, effectMutation);
    assert.deepEqual(prepared.metadata.transactionIdentity.effectPlan, plan);
    const request = { namespace: inspect, operationId: effectMutation.operationId, mutation: 1, recordId: effectMutation.effect.effectId,
      expectedVersion: effectMutation.expectedVersion, expectedPolicyDigest: digest, reason: effectMutation.reason, effectPlan: plan };
    const applied = await fixture.client.mutateState(request);
    assert.equal(applied.value.receipt.effect.fact, 1);
    assert.equal(applied.metadata.outcome, OutcomeKnowledge.Observed);
    const currentRead = { ...inspect, authorizationPublication: { ...publication, id: `publication:sha256:${"3".repeat(64)}` } };
    const recovered = await fixture.client.getStateOperationReceipt({ namespace: currentRead, operationId: effectMutation.operationId, originalEffectPlan: plan });
    assert.deepEqual(recovered.value.receipt.effect.originalPlan, plan);
    assert.equal(recovered.metadata.transactionIdentity.authorizationPublication.id, currentRead.authorizationPublication.id);
    assert.equal(recovered.metadata.transactionIdentity.effectMutation.effect.authorizationPublication.id, publication.id);
    assert.deepEqual(fixture.state.calls.map(call => call.operation), ["planEffectMutation", "mutateState", "getStateOperationReceipt"]);
    const before = fixture.state.calls.length;
    await assert.rejects(fixture.client.mutateState({ ...request, effectPlan: undefined }), error => !error.failure.dispatched);
    await assert.rejects(fixture.client.mutateState({ ...request, expectedVersion: new Uint8Array(32).fill(9) }), error => !error.failure.dispatched);
    await assert.rejects(fixture.client.planEffectMutation({ ...effectMutation, expectedVersion: new Uint8Array(32) }), error => !error.failure.dispatched);
    assert.equal(fixture.state.calls.length, before);
  } finally { await fixture.stop(); }
});

test("effect plan audit uncertainty preserves checked data without supplying a provider-confirmed fact", async () => {
  const fixture = await peer("effect-invalid");
  try {
    await assert.rejects(fixture.client.planEffectMutation({ ...effectMutation, reason: "bad-audit" }), error => {
      assert.equal(error.failure.outcome, OutcomeKnowledge.Unknown);
      assert.equal(error.failure.observedTransaction.kind, "effectPlan");
      assert.equal(error.failure.transactionIdentity.effectPlan.original.reason, "bad-audit");
      return true;
    });
    await assert.rejects(fixture.client.planEffectMutation({ ...effectMutation, reason: "bad-window" }), error => !error.failure.observedTransaction);
    const plan = effectPlan();
    await assert.rejects(fixture.client.mutateState({ namespace: inspect, operationId: effectMutation.operationId, mutation: 1,
      recordId: effectMutation.effect.effectId, expectedVersion: effectMutation.expectedVersion, expectedPolicyDigest: digest,
      reason: effectMutation.reason, effectPlan: plan }), error => !error.failure.observedTransaction);
    assert.equal(fixture.state.calls.length, 3);
  } finally { await fixture.stop(); }
});
function replyFor(operation, request) {
  const effect = { effectId: "effect-id", commandId: "command-id", commandAttemptId: "attempt-id", providerProfile: "approved-provider", disposition: 1 };
  const page = { returnedCount: 1, encodedBytes: 128n, nextCursor: Uint8Array.of(7) };
  switch (operation) {
    case "invokeCommand": { const command = inspected(); return { command, invocation: invoked({ case: "declaredError", value: command.businessRejection }) }; }
    case "query": return { invocation: invoked({ case: "success", value: { payload: Uint8Array.of(4), mediaType: "application/octet-stream" } }),
      view: { namespace, version: Uint8Array.of(3), stateSchema: "schema" }, source };
    case "lookupCommand": return { command: inspected() };
    case "lookupCommit": return { command: inspected(true) };
    case "getEffect": return { effect };
    case "listEffectHistory": return { receipts: [effect], page };
    case "cancelCommand": return { disposition: 3, command: inspected() };
    case "inspectNamespace": return { namespace: { view: { namespace, version: Uint8Array.of(3), stateSchema: "schema" },
      quota, status: 1, generation: 18446744073709551615n, engineProfile: "embedded-v1", engineProfileDigest: digest } };
    case "selectEntity": return { entities: [{ entity: "first", version: Uint8Array.of(3) }], page };
    case "planEffectMutation": return { plan: effectPlan(request) };
    case "mutateState": case "getStateOperationReceipt": return { receipt: request.effectPlan || request.originalEffectPlan
      ? effectReceipt(request.effectPlan ?? request.originalEffectPlan) : stateReceipt(request) };
    case "mutateNamespace": return { receipt: { operationId: request.operationId, receiptId: "namespace-receipt",
      namespace, mutation: 1, authenticatedOperator: "operator", afterGeneration: 1n, status: 1, stateSchema: "schema", disposition: 1 } };
    case "inspectDispatcher": return { dispatcher: { generation: { ownerEpoch: 18446744073709551615n, revision: 18446744073709551615n }, paused: true,
      failure: 1, physicalOwners: 18446744073709551615n } };
    case "controlDispatcher": return { receipt: dispatcherReceipt(request), published: true, paused: true };
    case "getDispatcherOperation": return { receipt: dispatcherReceipt(request.original) };
    default: throw new Error("unsupported fixture operation");
  }
}
async function peer(mode = "normal") {
  const server = createServer({ settings: { maxConcurrentStreams: 16 } });
  const state = { sessions: new Set(), connections: 0, calls: [] };
  server.on("session", (session) => { state.connections++; state.sessions.add(session); session.on("error", () => {}); session.on("close", () => state.sessions.delete(session)); });
  server.on("stream", (stream, headers) => {
    stream.on("error", () => {});
    const operationName = String(headers[":path"]).split("/").at(-1);
    const operation = operationName[0].toLowerCase() + operationName.slice(1);
    const descriptor = method(operation), chunks = [];
    stream.on("data", (chunk) => chunks.push(chunk));
    stream.on("end", () => {
      assert.equal(headers.authorization, `Bearer ${token}`);
      const frame = Buffer.concat(chunks), request = fromBinary(descriptor.input, frame.subarray(5));
      state.calls.push({ operation, request });
      if (mode === "hold" && operation === "invokeCommand") return;
      if (mode === "aborted") {
        stream.respond({ ":status": 200, "content-type": "application/grpc", "grpc-status": "10" }); stream.end(); return;
      }
      const value = replyFor(operation, request);
      if (mode === "substituted-activation") value.invocation.activationId = "different-activation";
      if (mode === "effect-invalid") {
        if (operation === "planEffectMutation" && request.reason === "bad-window") value.plan.expiresAtUnixMillis = 31001n;
        if (operation === "planEffectMutation" && request.reason === "bad-audit") value.auditAck = { status: 91 };
        if (operation === "mutateState") { value.receipt.effect.fact = 2; value.receipt.effect.providerReceipt = "forged-provider"; value.receipt.effect.providerObservedAtUnixMillis = 1400n; }
      }
      if (mode === "dispatcher-invalid") {
        if (operation === "controlDispatcher") {
          if (request.operationId === "dispatcher-original" && request.action === 1) value.auditAck = { status: 91 };
          if (request.operationId === "replayed") value.replayed = true;
          if (request.operationId === "not-committed") value.receipt.disposition = 2;
          if (request.action === 2) value.receipt.clockContinuityProven = false;
        }
        if (operation === "inspectDispatcher") { value.dispatcher.pendingControl = true; value.dispatcher.paused = false; }
        if (operation === "getDispatcherOperation" && request.original.operationId === "mismatch") value.receipt.afterGeneration.revision = 7n;
      }
      if (value.command !== undefined) value.command = wireInspection(value.command);
      const body = toBinary(descriptor.output, create(descriptor.output, value));
      const response = Buffer.alloc(body.length + 5); response.writeUInt32BE(body.length, 1); response.set(body, 5);
      const audit = mode === "bad-audit" ? { "latent-audit-status": "durable", "latent-audit-attempt": "0" } : {};
      stream.respond({ ":status": 200, "content-type": "application/grpc", ...audit }, { waitForTrailers: true });
      stream.on("wantTrailers", () => stream.sendTrailers({ "grpc-status": "0" })); stream.end(response);
    });
  });
  server.listen(0, "127.0.0.1"); await once(server, "listening");
  const client = new RpcClient({ endpoint: `http://127.0.0.1:${server.address().port}`, tenant: "tests", credential: Buffer.from(token) });
  return { client, state, stop: async () => { await client.shutdown(); for (const session of state.sessions) session.destroy(); await new Promise((resolve) => server.close(resolve)); } };
}

test("sixteen transaction operations share the maintained connection and retain exact receipts/pages", async () => {
  const fixture = await peer();
  try {
    const requests = [ ["invokeCommand", command], ["query", { profile: current, invocation: invoke, namespace }],
      ["lookupCommand", lookup], ["lookupCommit", { ...lookup, receiptId: "receipt-id" }], ["getEffect", { ...lookup, effectId: "effect-id" }],
      ["listEffectHistory", { effect: { ...lookup, effectId: "effect-id" }, page: { limit: 8 } }],
      ["cancelCommand", { command: lookup, reason: "caller request" }], ["inspectNamespace", inspect],
      ["mutateNamespace", { namespace: inspect, operationId: "create-original", mutation: 1, expectedGeneration: 0n, configuration: { stateSchema: "schema", quota } }],
      ["selectEntity", { namespace: inspect, page: { limit: 8 } }],
      ["mutateState", { namespace: inspect, operationId: "state-original", mutation: 4, expectedVersion: Uint8Array.of(1), expectedPolicyDigest: digest, reason: "checkpoint" }],
      ["getStateOperationReceipt", { namespace: inspect, operationId: "state-original" }],
      ["planEffectMutation", effectMutation],
      ["inspectDispatcher", { profile: current, scope: 1 }], ["controlDispatcher", dispatcherControl],
      ["getDispatcherOperation", { original: dispatcherControl }] ];
    for (const [operation, request] of requests) {
      const response = await fixture.client[operation](request);
      if (!["inspectDispatcher", "controlDispatcher", "getDispatcherOperation"].includes(operation)) assert.ok(response.metadata.transactionIdentity.namespace);
      else assert.equal(response.metadata.transactionIdentity.namespace, undefined);
      if (operation === "invokeCommand") { assert.equal(response.value.command.outcome, CommandOutcome.Rejected); assert.equal(response.metadata.observedTransaction.command.success, undefined); }
      if (operation === "inspectNamespace") assert.equal(response.value.namespace.generation, 18446744073709551615n);
      if (operation === "selectEntity" || operation === "listEffectHistory") assert.deepEqual(response.value.page.nextCursor, Uint8Array.of(7));
      if (operation === "mutateNamespace") assert.equal(response.metadata.transactionIdentity.expectedGeneration, 0n);
      if (operation === "inspectDispatcher") assert.equal(response.value.dispatcher.physicalOwners, 18446744073709551615n);
      if (operation === "controlDispatcher" || operation === "getDispatcherOperation") {
        assert.equal(response.metadata.transactionIdentity.dispatcherExpectedGeneration.revision, 18446744073709551614n);
        assert.equal(response.metadata.observedTransaction.kind, "dispatcher");
      }
    }
    assert.equal(fixture.state.connections, 1); assert.equal(fixture.state.calls.length, 16);
  } finally { await fixture.stop(); }
  assert.deepEqual(fixture.client.usage(), { activeCalls: 0, reservedMessageBytes: 0, sessions: 0, sockets: 0, closed: true });
});

test("dispatcher recovery preserves original generations and independent durable/audit observations", async () => {
  const fixture = await peer("dispatcher-invalid");
  try {
    await assert.rejects(fixture.client.controlDispatcher(dispatcherControl), error => {
      assert.equal(error.failure.outcome, OutcomeKnowledge.Observed);
      assert.equal(error.failure.observedTransaction.kind, "dispatcher");
      assert.equal(error.failure.observedTransaction.receipt.receiptId, "dispatcher-receipt");
      assert.equal(error.failure.unsupportedWireValue.value, "91");
      assert.deepEqual(error.failure.transactionIdentity.dispatcherExpectedGeneration, dispatcherControl.expectedGeneration);
      assert.equal(error.failure.transactionIdentity.expectedAbort, undefined); return true;
    });
    const recovered = await fixture.client.getDispatcherOperation({ original: dispatcherControl });
    assert.equal(recovered.metadata.observedTransaction.receipt.receiptId, "dispatcher-receipt");
    assert.equal(fixture.state.calls.length, 2);
    for (const request of [{ ...dispatcherControl, operationId: "replayed" }, { ...dispatcherControl, operationId: "not-committed" }, { ...dispatcherControl, action: 2 }])
      await assert.rejects(fixture.client.controlDispatcher(request), error => {
        assert.equal(error.failure.category, FailureCategory.Decode); assert.equal(error.failure.observedTransaction, undefined); return true;
      });
    await assert.rejects(fixture.client.inspectDispatcher({ profile: current, scope: 1 }), error => {
      assert.equal(error.failure.category, FailureCategory.Decode); return true;
    });
    await assert.rejects(fixture.client.getDispatcherOperation({ original: { ...dispatcherControl, operationId: "mismatch" } }), error => {
      assert.equal(error.failure.observedTransaction, undefined); return true;
    });
    const before = fixture.state.calls.length;
    await assert.rejects(fixture.client.controlDispatcher({ ...dispatcherControl, expectedGeneration: { ownerEpoch: 1n, revision: 18446744073709551615n } }), error => {
      assert.equal(error.failure.dispatched, false); assert.equal(error.failure.transactionIdentity.dispatcherExpectedGeneration.revision, 18446744073709551615n); return true;
    });
    assert.equal(fixture.state.calls.length, before);
  } finally { await fixture.stop(); }
});

test("command and query reject a substituted activation identity", async () => {
  const fixture = await peer("substituted-activation");
  try {
    for (const operation of [() => fixture.client.invokeCommand(command), () => fixture.client.query({ profile: current, invocation: invoke, namespace })])
      await assert.rejects(operation(), error => {
        assert.equal(error.failure.category, FailureCategory.Decode); assert.equal(error.failure.transactionIdentity.activationId, "activation-original");
        assert.equal(error.failure.observedTransaction, undefined); return true;
      });
    assert.equal(fixture.state.calls.length, 2);
  } finally { await fixture.stop(); }
});

test("durable business rejection remains recoverable through later audit failure", async () => {
  const fixture = await peer("bad-audit");
  try {
    await assert.rejects(fixture.client.lookupCommand(lookup), (error) => {
      assert.ok(error instanceof RpcError); assert.equal(error.failure.category, FailureCategory.Decode);
      assert.equal(error.failure.outcome, OutcomeKnowledge.Observed);
      assert.equal(error.failure.observedTransaction.command.outcome, CommandOutcome.Rejected);
      assert.equal(error.failure.observedTransaction.command.businessRejection, undefined);
      assert.equal(error.failure.transactionIdentity.command.clientKey, "business-key");
      assert.equal(error.failure.transactionIdentity.fingerprintSha256.length, 32); return true;
    });
    assert.equal(fixture.state.calls.length, 1);
  } finally { await fixture.stop(); }
});

test("grpc ABORTED never proves a new attempt or resubmits a command", async () => {
  const fixture = await peer("aborted");
  try {
    await assert.rejects(fixture.client.invokeCommand(command), (error) => {
      assert.equal(error.failure.outcome, OutcomeKnowledge.Unknown);
      assert.equal(error.failure.observedTransaction, undefined);
      assert.equal(error.failure.transactionIdentity.expectedAbort, undefined);
      assert.deepEqual(error.failure.transactionIdentity.expectedVersions, command.expectedVersions); return true;
    });
    assert.equal(fixture.state.calls.length, 1);
  } finally { await fixture.stop(); }
});

test("AbortSignal retires the physical call and a fresh signal explicitly recovers original identity", async () => {
  const fixture = await peer("hold"), abort = new AbortController(), input = structuredClone(command);
  try {
    const pending = fixture.client.invokeCommand(input, { signal: abort.signal });
    input.command.clientKey = "changed-after-call"; input.expectedVersions[0].version[0] = 99;
    await new Promise((resolve) => setTimeout(resolve, 30)); abort.abort();
    await assert.rejects(pending, (error) => {
      assert.equal(error.failure.category, FailureCategory.LocalCancelled); assert.equal(error.failure.outcome, OutcomeKnowledge.Unknown);
      assert.equal(error.failure.transactionIdentity.command.clientKey, "business-key");
      assert.deepEqual(error.failure.transactionIdentity.expectedVersions, command.expectedVersions); return true;
    });
    for (let count = 0; fixture.client.usage().activeCalls !== 0 && count < 20; count++) await new Promise((resolve) => setTimeout(resolve, 5));
    assert.equal(fixture.client.usage().activeCalls, 0);
    const recovered = await fixture.client.lookupCommand(lookup, { signal: new AbortController().signal });
    assert.equal(recovered.value.command.outcome, CommandOutcome.Rejected);
    assert.equal(fixture.state.calls.length, 2); assert.equal(fixture.state.calls[0].request.command.clientKey, "business-key");
  } finally { await fixture.stop(); }
});

test("Phase 4 wire boundaries keep all integer bits and reject malformed ownership shapes", () => {
  const schema = method("lookupCommand").output;
  const value = inspected(), encoded = toBinary(schema, create(schema, { command: wireInspection(value) }));
  assert.equal(decode(schema, encoded, 262144, true).command.source.routeGeneration, 18446744073709551615n);
  assert.throws(() => decode(schema, Buffer.concat([encoded, encoded]), 262144, true), ShapeError);
  const selected = method("invokeCommand").input;
  const invalid = { ...command, expectedVersions: [{ key: Uint8Array.of(1), absent: true, version: Uint8Array.of(2) }] };
  assert.throws(() => encode(selected, invalid, 262144, true), ShapeError);
  const future = inspected(); future.outcome = 91;
  const parsed = decode(schema, toBinary(schema, create(schema, { command: wireInspection(future) })), 262144, true);
  assert.equal(parsed.command.outcome, 91);
  assert.throws(() => validateResponse("lookupCommand", lookup, parsed, "tests"), (error) => error.unsupportedWireValue?.value === "91");
  const retained = inspected(); retained.retention = { recordFormat: "old-supported-v1", recordVersion: 1, payloadAvailable: false, requiredRecordIds: Array.from({ length: 256 }, (_, index) => `record-${index}`) };
  delete retained.businessRejection;
  const expiry = decode(schema, toBinary(schema, create(schema, { command: retained })), 262144, true);
  validateResponse("lookupCommand", lookup, expiry, "tests"); assert.equal(expiry.command.retention.requiredRecordIds.length, 256);
});

test("wrong profile selection fails before opening a connection and keeps the original key", async () => {
  const fixture = await peer();
  try {
    await assert.rejects(fixture.client.invokeCommand({ ...command, profile: { ...current, hostAbiDigest: digest } }), (error) => {
      assert.equal(error.failure.category, FailureCategory.InvalidRequest); assert.equal(error.failure.dispatched, false);
      assert.equal(error.failure.transactionIdentity.command.clientKey, "business-key"); return true;
    });
    assert.equal(fixture.state.connections, 0); assert.equal(fixture.state.calls.length, 0);
  } finally { await fixture.stop(); }
});
