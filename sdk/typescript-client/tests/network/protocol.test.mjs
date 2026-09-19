import test from "node:test";
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { BinaryWriter, WireType } from "@bufbuild/protobuf/wire";
import { encode, decode } from "../../dist/node/protocol/codec.js";
import { method, registry } from "../../dist/node/protocol/schema.js";
import { sourceDigest } from "../../dist/node/protocol/generated.js";
import { RpcClient } from "../../dist/node/index.js";
import { audit } from "../../dist/node/errors.js";
import { peer, request, token } from "./peer.mjs";

test("compiled descriptors match normalized authoritative source identities", () => {
  const root = new URL("../../../../", import.meta.url);
  const profile = JSON.parse(readFileSync(new URL("sdk/profile/client-profile.json", root)));
  const hash = createHash("sha256");
  for (const path of Object.keys(profile.sources).sort()) {
    hash.update(path).update("\0").update(readFileSync(new URL(path, root), "utf8").replaceAll("\r\n", "\n")).update("\0");
  }
  assert.equal(sourceDigest, `sha256:${hash.digest("hex")}`);
  for (const operation of profile.operations) {
    const key = operation.name[0].toLowerCase() + operation.name.slice(1);
    const descriptor = method(key);
    assert.equal(descriptor.parent.typeName, operation.service);
    assert.equal(descriptor.input.name, operation.request);
    assert.equal(descriptor.output.name, operation.response);
  }
});

test("wire codec preserves empty versus absent IDs, all u64 bits and unknown enum numbers", () => {
  const schema = method("invoke").input;
  for (const activationId of [undefined, "", "known"]) {
    const value = request();
    if (activationId === undefined) delete value.activationId; else value.activationId = activationId;
    value.deadlineUnixMillis = 18446744073709551615n;
    value.budget.wallTimeLimitMillis = 0n;
    const decoded = decode(schema, encode(schema, value, 65536), 65536);
    assert.equal(decoded.activationId, activationId);
    assert.equal(decoded.deadlineUnixMillis, 18446744073709551615n);
    assert.equal(decoded.budget.wallTimeLimitMillis, 0n);
  }
  const cancel = method("cancel").output;
  assert.equal(decode(cancel, encode(cancel, { disposition: -73 }, 1024), 1024).disposition, -73);
  const invalid = request();
  invalid.budget.cpuFuel = Number.MAX_SAFE_INTEGER;
  assert.throws(() => encode(schema, invalid, 65536));
});

test("returned payloads own only their exact bytes, not the reserved receive buffer", () => {
  const schema = method("invoke").input;
  const encoded = encode(schema, request("owned", "bytes"), 65536);
  const allocation = Buffer.alloc(65536);
  allocation.set(encoded);
  const decoded = decode(schema, allocation.subarray(0, encoded.length), 65536);
  assert.equal(decoded.payload.buffer.byteLength, 5);
  allocation.fill(0);
  assert.equal(Buffer.from(decoded.payload).toString(), "bytes");
});

test("preflight rejects oneof ambiguity, duplicate maps, overlong varints, groups and bounded collection exhaustion", () => {
  const invocation = method("invoke").output;
  const ambiguous = new BinaryWriter().tag(5, WireType.LengthDelimited).bytes(new Uint8Array()).tag(8, WireType.LengthDelimited).bytes(new Uint8Array()).finish();
  assert.throws(() => decode(invocation, ambiguous, 65536));
  assert.throws(() => decode(invocation, Uint8Array.from([0x28, ...new Array(20).fill(0x80)]), 65536));
  assert.throws(() => decode(invocation, Uint8Array.from([0x0b, 0x0c]), 65536));
  const metadata = registry.getMessage("latent.control.v1.ObjectMetadata");
  const entry = new BinaryWriter().tag(1, WireType.LengthDelimited).string("duplicate").tag(2, WireType.LengthDelimited).string("value").finish();
  const duplicate = new BinaryWriter().tag(4, WireType.LengthDelimited).bytes(entry).tag(4, WireType.LengthDelimited).bytes(entry).finish();
  assert.throws(() => decode(metadata, duplicate, 65536));
  const list = method("listCapabilities").output;
  const writer = new BinaryWriter();
  for (let index = 0; index < 129; index++) writer.tag(1, WireType.LengthDelimited).bytes(new Uint8Array());
  assert.throws(() => decode(list, writer.finish(), 65536));
  const unknown = new BinaryWriter().tag(150, WireType.Varint).uint32(17).finish();
  assert.equal(decode(method("cancel").output, unknown, 65536).disposition, 0);
});

test("input collections, map keys and invalid UTF16 fail before encoding work can grow", () => {
  const schema = method("invoke").input;
  const value = request();
  value.metadata = { ["a".repeat(129)]: "value" };
  assert.throws(() => encode(schema, value, 65536));
  value.metadata = {};
  value.activationId = "\ud800";
  assert.throws(() => encode(schema, value, 65536));
  const capabilities = method("listCapabilities").output;
  const sparse = new Array(2);
  sparse[1] = {};
  assert.throws(() => encode(capabilities, { capabilities: sparse }, 65536));
});

test("audit absence, uncertainty and future values remain distinct without fabricated acknowledgement", () => {
  assert.deepEqual(audit(new Map()), {});
  const known = audit(new Map([["latent-audit-status", "durable"], ["latent-audit-attempt", "18446744073709551615"]]));
  assert.equal(known.auditAck.attemptSequence, 18446744073709551615n);
  assert.deepEqual(audit(new Map([["latent-audit-status", "future-state"]])), { auditStatus: "future-state" });
  assert.deepEqual(audit(new Map([["latent-audit-status", "future-durable-v2"], ["latent-audit-attempt", "18446744073709551615"]])),
    { auditStatus: "future-durable-v2", auditAttemptSequence: 18446744073709551615n });
  for (const attempt of ["0", "01", "18446744073709551616"]) assert.throws(() => audit(new Map([["latent-audit-status", "durable"], ["latent-audit-attempt", attempt]])));
  assert.throws(() => audit(new Map([["latent-audit-attempt", "1"]])));
});

test("private entry configuration rejects ambient/remote authority and local failures open no sockets", async () => {
  const config = { endpoint: "http://127.0.0.1:9080", tenant: "tests", credential: Buffer.from(token) };
  for (const endpoint of ["http://example.com:9080", "http://192.0.2.1:9080", "http://user:private@127.0.0.1:9080", "http://127.1:9080", "http://127.0.0.1:9080/path", "http://[::ffff:127.0.0.1]:9080"]) {
    assert.throws(() => new RpcClient({ ...config, endpoint }), (error) => !String(error).includes("private@"));
  }
  const client = new RpcClient(config);
  await assert.rejects(client.invoke(request(), { timeoutMillis: 0n }), (error) => !error.failure.dispatched);
  await assert.rejects(client.invoke(request(), { timeoutMillis: 18446744073709551615n }), (error) => !error.failure.dispatched);
  const controller = new AbortController();
  controller.abort();
  await assert.rejects(client.invoke(request(), { signal: controller.signal }), (error) => !error.failure.dispatched);
  await assert.rejects(client.listPolicies({ recordKind: 1, page: { pageSize: 0 } }));
  assert.equal(client.usage().sockets, 0);
  await client.shutdown();
});

test("caller mutations cannot change retained request identity or owned credential", async () => {
  const server = await peer();
  const credential = Buffer.from(token);
  const client = server.client({ credential });
  try {
    credential.fill(0);
    const original = request("captured");
    const pending = client.invoke(original);
    original.activationId = "mutated";
    original.payload.fill(0);
    assert.equal((await pending).value.activationId, "captured");
  } finally { await client.shutdown(); await server.stop(); }
});
