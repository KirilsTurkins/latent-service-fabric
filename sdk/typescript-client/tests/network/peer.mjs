import { createServer } from "node:http2";
import { once } from "node:events";
import { create, fromBinary, toBinary } from "@bufbuild/protobuf";
import { method, registry } from "../../dist/node/protocol/schema.js";
import { RpcClient } from "../../dist/node/index.js";

export const token = "LSF-PUBLIC-NODE-CLIENT-FIXTURE-ONLY";

export async function peer() {
  const server = createServer({ settings: { maxConcurrentStreams: 32 } });
  const state = { connections: 0, open: new Set(), calls: 0, cancellations: 0, mutations: 0, activations: new Map(), policies: new Map(), headers: [] };
  server.on("session", (session) => {
    state.connections++;
    state.open.add(session);
    session.on("error", () => {});
    session.on("close", () => state.open.delete(session));
  });
  server.on("stream", (stream, headers) => {
    stream.on("error", () => {});
    const name = String(headers[":path"]).split("/").at(-1);
    const operation = name[0].toLowerCase() + name.slice(1);
    const descriptor = method(operation);
    const chunks = [];
    let size = 0;
    stream.on("data", (chunk) => {
      size += chunk.length;
      if (size > 1048576) stream.destroy(); else chunks.push(chunk);
    });
    stream.on("end", () => {
      if (stream.destroyed) return;
      const frame = Buffer.concat(chunks);
      if (frame.length < 5 || frame.readUInt32BE(1) !== frame.length - 5) { stream.destroy(); return; }
      const request = fromBinary(descriptor.input, frame.subarray(5));
      if (headers.authorization !== `Bearer ${token}`) { error(stream, 16); return; }
      state.headers.push({ timeout: headers["grpc-timeout"], path: headers[":path"] });
      if (operation === "invoke") {
        if (request.target?.tenant !== "tests") { error(stream, 7); return; }
        const id = request.activationId ?? "server-assigned";
        if (!id) { error(stream, 3); return; }
        state.calls++;
        state.activations.set(id, { activationId: id, phase: "running" });
        const mode = Buffer.from(request.payload).toString();
        if (mode === "hold") return;
        const value = { activationId: mode === "wrong-id" ? "different-id" : id, revisionId: "revision", releaseDigest: `sha256:${"1".repeat(64)}`, routeGeneration: 18446744073709551615n, consumption: {},
          result: mode === "declared" ? { case: "declaredError", value: { code: "application-failure", payload: Buffer.from("declared") } }
            : mode === "platform" ? { case: "platformFailure", value: { code: "permission-denied" } }
              : { case: "success", value: { payload: mode === "oversize" ? Buffer.alloc(8192) : request.payload, mediaType: "application/octet-stream" } } };
        if (mode === "malformed") { reply(stream, Buffer.from([0xff]), {}); return; }
        if (mode === "rpc-detail") {
          const schema = registry.getMessage("latent.control.v1.PlatformError");
          const encoded = toBinary(schema, create(schema, { code: "permission-denied", message: "private-peer-diagnostic", retryable: true }));
          error(stream, 7, { "grpc-status-details-bin": Buffer.from(encoded).toString("base64") });
          return;
        }
        send(stream, descriptor.output, value);
      } else if (operation === "cancel") {
        if (request.activationId === "future-disposition") { send(stream, descriptor.output, { disposition: 73 }); return; }
        state.cancellations++;
        const status = state.activations.get(request.activationId);
        if (!status) send(stream, descriptor.output, { disposition: 3 });
        else if (status.terminalState) send(stream, descriptor.output, { disposition: 2, terminalState: status.terminalState });
        else {
          status.terminalState = "cancelled";
          status.finalConsumption = {};
          status.terminalAtUnixMillis = 1n;
          status.terminalOutcome = { case: "platformFailure", value: { code: "cancelled" } };
          send(stream, descriptor.output, { disposition: 1 });
        }
      } else if (operation === "getActivation") {
        const status = state.activations.get(request.activationId);
        if (status) send(stream, descriptor.output, status); else error(stream, 5);
      } else if (operation === "applyPolicy") {
        const existing = state.policies.get(request.operationId);
        if (existing) {
          if (!existing.frame.equals(frame)) { error(stream, 9); return; }
          send(stream, descriptor.output, existing.value, auditHeaders());
          return;
        }
        const policy = { ...request.policy, generation: 2n, contentDigest: `sha256:${"2".repeat(64)}` };
        const receipt = { operationId: request.operationId, tenant: "tests", id: policy.id, recordKind: policy.recordKind, generation: policy.generation, contentDigest: policy.contentDigest, revoked: false };
        const value = { policy, receipt };
        state.policies.set(request.operationId, { value, frame });
        state.mutations++;
        if (request.operationId === "lost-operation") return;
        send(stream, descriptor.output, value, auditHeaders());
      } else if (operation === "getPolicyOperation") {
        const known = state.policies.get(request.operationId);
        send(stream, descriptor.output, known ? { receipt: known.value.receipt } : {});
      } else if (operation === "getPolicy") {
        const policy = [...state.policies.values()].map((entry) => entry.value.policy).find((entry) => entry.id === request.id);
        send(stream, descriptor.output, policy ? { policy } : {});
      } else if (operation === "listPolicies") {
        const policies = [...state.policies.values()].map((entry) => entry.value.policy).slice(0, request.page?.pageSize ?? 0);
        send(stream, descriptor.output, { policies, page: {}, catalogGeneration: 18446744073709551615n });
      } else if (operation === "listCapabilities") {
        send(stream, descriptor.output, { capabilities: [{ id: "http", contract: "latent:http/client@0.2.0", provider: "http", operations: ["send"], inspection: { providerConfigurationEpoch: 18446744073709551615n, providerProfile: "bounded-http-v1", state: "current" } }], page: {}, state: "current" });
      }
    });
  });
  server.listen(0, "127.0.0.1");
  await once(server, "listening");
  const config = { endpoint: `http://127.0.0.1:${server.address().port}`, tenant: "tests", credential: Buffer.from(token) };
  return { state, config, client: (changes = {}) => new RpcClient({ ...config, ...changes }), stop: async () => {
    for (const session of state.open) session.destroy();
    await new Promise((resolve) => server.close(resolve));
  } };
}

function send(stream, schema, value, metadata = {}) { reply(stream, toBinary(schema, create(schema, value)), metadata); }

function reply(stream, bytes, metadata) {
  stream.respond({ ":status": 200, "content-type": "application/grpc", ...metadata }, { waitForTrailers: true });
  stream.on("wantTrailers", () => stream.sendTrailers({ "grpc-status": "0" }));
  const frame = Buffer.alloc(bytes.length + 5);
  frame.writeUInt32BE(bytes.length, 1);
  frame.set(bytes, 5);
  stream.end(frame);
}

function error(stream, code, metadata = {}) {
  stream.respond({ ":status": 200, "content-type": "application/grpc", "grpc-status": String(code), ...metadata }, { endStream: true });
}

function auditHeaders() { return { "latent-audit-status": "durable", "latent-audit-attempt": "18446744073709551615" }; }

export function request(id = "call", mode = "success") {
  return { activationId: id, target: { tenant: "tests", service: "example", contract: "tests:example/api@1.0.0", function: "run" }, payload: Buffer.from(mode), mediaType: "application/octet-stream", priority: 0, metadata: {},
    budget: { cpuFuel: 10000n, memoryBytes: 65536n, wallTimeLimitMillis: 1000n, childCalls: 0, outboundRequests: 1, stateReadBytes: 0n, stateWriteBytes: 0n, blobReadBytes: 32n, blobWriteBytes: 32n, logBytes: 0n, effectCount: 0 } };
}

export function policy(operationId = "create") { return { operationId, expectedGeneration: 0n, policy: { id: "policy", document: "{}", generation: 0n, language: "", recordKind: 1, contentDigest: "", revoked: false } }; }

export async function until(predicate) {
  const deadline = Date.now() + 3000;
  while (!predicate()) {
    if (Date.now() > deadline) throw new Error("peer observation deadline");
    await new Promise((resolve) => setTimeout(resolve, 1));
  }
}
