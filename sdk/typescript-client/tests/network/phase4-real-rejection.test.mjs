// Explicit rejection and recovery probes against a separately provisioned node.
import assert from "node:assert/strict";
import test from "node:test";
import { RpcClient } from "../../dist/node/index.js";
import { currentProfile, CommandOutcome } from "../../dist/transactions.js";
function required(name) { const value = process.env[name]; assert.ok(value, `missing fixture field: ${name}`); return value; }
function selector(tenant) { return { namespace: { tenant, namespace: required("LSF_401_NAMESPACE"), incarnation: required("LSF_401_INCARNATION") },
  operation: "update", clientKey: "typescript-sdk-rejected-command" }; }
function owner(tenant) { return new RpcClient({ endpoint: `http://${required("LSF_401_ENDPOINT")}`, tenant, credential: Buffer.from(required("LSF_401_TOKEN")) }); }
async function retire(client) { await client.shutdown(); const usage = client.usage(); assert.equal(usage.activeCalls, 0);
  assert.equal(usage.reservedMessageBytes, 0); assert.equal(usage.sessions, 0); assert.equal(usage.sockets, 0); assert.equal(usage.closed, true); }
test("durable rejection leaves the business key unchanged", { skip: process.env.LSF_401_MODE !== "reject" }, async () => {
  const tenant = required("LSF_401_TENANT"), version = required("LSF_401_EXPECTED_VERSION_HEX");
  assert.match(version, /^(?:[0-9a-f]{2})+$/); const client = owner(tenant);
  try {
    const invocation = { activationId: "typescript-sdk-rejected-command", target: { tenant, service: "examples/transaction-java-aggregate",
      contract: "examples:transactional-aggregate/api@1.0.0", function: "update", route: "transaction-java-aggregate" },
      payload: Buffer.from('[{"delta":1,"reject":true}]'), mediaType: "application/vnd.latent.wit-values.v1+json", priority: 0,
      metadata: {}, budget: { cpuFuel: 1000000000n, memoryBytes: 67108864n, childCalls: 0, outboundRequests: 0,
        stateReadBytes: 4194304n, stateWriteBytes: 2097152n, blobReadBytes: 0n, blobWriteBytes: 0n, logBytes: 0n,
        effectCount: 1, wallTimeLimitMillis: 120000n } };
    const result = (await client.invokeCommand({ profile: currentProfile(), command: selector(tenant), invocation,
      inputFormat: "lsf-wit-values-v1", expectedVersions: [{ key: Buffer.from("aggregate/count"), version: Buffer.from(version,"hex") }] })).value;
    const command = result.command, rejection = result.invocation?.declaredError;
    assert.ok(command && rejection && command.outcome === CommandOutcome.Rejected && command.metadataDurable
      && !command.applicationStateCommitted && !command.commit);
    assert.ok(rejection.code && rejection.payload.length);
    console.log(`REJECTION ${command.commandId} ${command.attemptId} ${Buffer.from(command.fingerprintSha256).toString("hex")} ${Buffer.from(rejection.code).toString("hex")} ${Buffer.from(rejection.payload).toString("hex")}`);
  } finally { await retire(client); }
});
test("original rejection recovers after a later state change", { skip: process.env.LSF_401_MODE !== "recover" }, async () => {
  const tenant = required("LSF_401_TENANT"), client = owner(tenant);
  try {
    const command = (await client.lookupCommand({ profile: currentProfile(), command: selector(tenant),
      authorizationPublication: { tenant, id: required("LSF_401_PUBLICATION") } })).value.command;
    assert.ok(command && command.outcome === CommandOutcome.Rejected && command.metadataDurable && !command.applicationStateCommitted && !command.commit);
    assert.equal(command.commandId, required("LSF_401_REJECTION_ID")); assert.equal(command.attemptId, required("LSF_401_REJECTION_ATTEMPT"));
    assert.equal(Buffer.from(command.fingerprintSha256).toString("hex"), required("LSF_401_REJECTION_FINGERPRINT"));
    assert.equal(Buffer.from(command.businessRejection.code).toString("hex"), required("LSF_401_REJECTION_CODE"));
    assert.equal(Buffer.from(command.businessRejection.payload).toString("hex"), required("LSF_401_REJECTION_PAYLOAD"));
    console.log("REJECTION_RECOVERED");
  } finally { await retire(client); }
});
