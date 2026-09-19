import test from "node:test";
import assert from "node:assert/strict";
import { inspect } from "node:util";
import { peer, policy, request, until } from "./peer.mjs";
import { FailureCategory as Category, OutcomeKnowledge as Knowledge } from "../../dist/management.js";

test("one real HTTP2 connection, exact full-width values, distinct outcomes and physical shutdown", async () => {
  const server = await peer();
  const client = server.client();
  try {
    assert.equal(client.usage().sockets, 0);
    const success = await client.invoke(request("success"));
    assert.equal(success.value.routeGeneration, 18446744073709551615n);
    assert.equal(Buffer.from(success.value.success.payload).toString(), "success");
    assert.equal((await client.invoke(request("declared", "declared"))).value.declaredError.code, "application-failure");
    assert.equal((await client.invoke(request("platform", "platform"))).value.platformFailure.code, "permission-denied");
    assert.equal(server.state.connections, 1);
    await client.shutdown();
    assert.deepEqual(client.usage(), { activeCalls: 0, reservedMessageBytes: 0, sessions: 0, sockets: 0, closed: true });
    await until(() => server.state.open.size === 0);
  } finally { await client.shutdown(); await server.stop(); }
});

test("local AbortSignal does not cancel the guest and original ID recovers status", async () => {
  const server = await peer();
  const client = server.client();
  try {
    const controller = new AbortController();
    const pending = client.invoke(request("lost", "hold"), { signal: controller.signal });
    const rejected = assert.rejects(pending, (error) => error.failure.category === Category.LocalCancelled && error.failure.outcome === Knowledge.Unknown && error.failure.identity.activationId === "lost");
    await until(() => server.state.calls === 1);
    controller.abort();
    await rejected;
    assert.equal(server.state.cancellations, 0);
    assert.equal((await client.getActivation({ activationId: "lost" })).value.phase, "running");
    assert.equal((await client.cancel({ activationId: "lost", reason: "explicit" })).value.disposition, 1);
    assert.equal((await client.getActivation({ activationId: "lost" })).value.terminalState, "cancelled");
    assert.equal(server.state.calls, 1);
  } finally { await client.shutdown(); await server.stop(); }
});

test("one absolute deadline and finite call admission never replay", async () => {
  const server = await peer();
  const client = server.client({ limits: { maximumCalls: 1 } });
  try {
    const pending = client.invoke(request("bounded", "hold"), { timeoutMillis: 150n });
    const rejected = assert.rejects(pending, (error) => error.failure.category === Category.Deadline && error.failure.outcome === Knowledge.Unknown);
    await until(() => server.state.calls === 1);
    await assert.rejects(client.invoke(request("excess")), (error) => error.failure.category === Category.Limit && !error.failure.dispatched);
    assert(client.usage().reservedMessageBytes > 0);
    await rejected;
    assert.equal(server.state.calls, 1);
    assert.match(server.state.headers[0].timeout, /^[0-9]{1,8}m$/);
  } finally { await client.shutdown(); await server.stop(); }
});

test("concurrent shutdown cancels pending waits and reaps the shared physical owners", async () => {
  const server = await peer();
  const client = server.client({ limits: { maximumCalls: 4 } });
  try {
    const pending = Array.from({ length: 4 }, (_, index) => assert.rejects(
      client.invoke(request(`shutdown-${index}`, "hold")),
      (error) => error.failure.category === Category.LocalCancelled && error.failure.outcome === Knowledge.Unknown,
    ));
    await until(() => server.state.calls === 4);
    const first = client.shutdown();
    const concurrent = client.shutdown();
    assert.equal(first, concurrent);
    await assert.rejects(client.invoke(request("too-late")), (error) => !error.failure.dispatched);
    await Promise.all([...pending, first, concurrent]);
    assert.deepEqual(client.usage(), { activeCalls: 0, reservedMessageBytes: 0, sessions: 0, sockets: 0, closed: true });
    await until(() => server.state.open.size === 0);
    assert.equal(server.state.connections, 1);
    assert.equal(server.state.cancellations, 0);
  } finally { await client.shutdown(); await server.stop(); }
});

test("a failed established connection is never silently replaced", async () => {
  const server = await peer();
  const client = server.client();
  try {
    await client.invoke(request("before-disconnect"));
    for (const session of server.state.open) session.destroy();
    await until(() => client.usage().sessions === 0 && client.usage().sockets === 0);
    await assert.rejects(client.invoke(request("after-disconnect")), (error) => error.failure.category === Category.Transport && !error.failure.dispatched);
    assert.equal(server.state.connections, 1);
    assert.equal(server.state.calls, 1);
  } finally { await client.shutdown(); await server.stop(); }
});

test("uncertain mutation retains ID, no receipt is unknown and explicit exact replay executes once", async () => {
  const server = await peer();
  const client = server.client();
  try {
    const original = policy("lost-operation");
    await assert.rejects(client.applyPolicy(original, { timeoutMillis: 100n }), (error) => error.failure.identity.operationId === "lost-operation" && error.failure.outcome === Knowledge.Unknown);
    const lookup = await client.getPolicyOperation({ operationId: "lost-operation" });
    const replay = await client.applyPolicy(original);
    assert.deepEqual(replay.value.receipt, lookup.value.receipt);
    assert.equal(replay.metadata.auditAck.attemptSequence, 18446744073709551615n);
    assert.equal(server.state.mutations, 1);
    const unknown = await client.getPolicyOperation({ operationId: "unknown" });
    assert.equal(unknown.value.receipt, undefined);
    assert.equal(unknown.metadata.outcome, Knowledge.Unknown);
    for (const pending of [client.getPolicyOperation({ operationId: "rpc-not-found" }),
      client.getActivation({ activationId: "never-observed" })]) {
      await assert.rejects(pending, (error) => error.failure.grpcStatus === 5
        && error.failure.outcome === Knowledge.Unknown);
    }
    const list = await client.listPolicies({ recordKind: 1, page: { pageSize: 1 } });
    assert.equal(list.value.policies.length, 1);
    assert.equal(list.value.catalogGeneration, 18446744073709551615n);
    const bindings = await client.listCapabilities({ deploymentId: "deployed", page: { pageSize: 1 }, includeNodeUsage: false });
    assert.equal(bindings.value.capabilities[0].inspection.providerConfigurationEpoch, 18446744073709551615n);
    const defaults = await client.listCapabilities({ deploymentId: "deployed" });
    assert.equal(defaults.value.capabilities.length, 1);
    const zero = await client.listCapabilities({ deploymentId: "deployed", page: { pageSize: 0 } });
    assert.equal(zero.value.capabilities.length, 1);
  } finally { await client.shutdown(); await server.stop(); }
});

test("tenant rejection, typed RPC details, malformed frames, reply bounds and identity mismatch stay separate", async () => {
  const server = await peer();
  const client = server.client();
  const foreign = server.client({ tenant: "foreign" });
  const small = server.client({ limits: { maximumResponseBytes: 128 } });
  try {
    const foreignRequest = request("foreign");
    foreignRequest.target.tenant = "foreign";
    await assert.rejects(foreign.invoke(foreignRequest), (error) => error.failure.grpcStatus === 7 && error.failure.category === Category.Rpc);
    await assert.rejects(client.invoke(request("detail", "rpc-detail")), (error) => {
      assert.equal(error.failure.platformError.code, "permission-denied");
      assert(!inspect(error).includes("private-peer-diagnostic"));
      return error.failure.grpcStatus === 7;
    });
    for (const mode of ["wrong-id", "malformed"]) await assert.rejects(client.invoke(request(mode, mode)), (error) => error.failure.category === Category.Decode && error.failure.outcome === Knowledge.Unknown);
    await assert.rejects(client.cancel({ activationId: "future-disposition", reason: "check" }), (error) => error.failure.unsupportedWireValue?.value === "73" && error.failure.grpcStatus === 0);
    await assert.rejects(small.invoke(request("oversize", "oversize")), (error) => error.failure.category === Category.Limit && error.failure.dispatched);
  } finally { await Promise.all([client.shutdown(), foreign.shutdown(), small.shutdown()]); await server.stop(); }
});
