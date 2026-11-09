// Explicit lost-response and fresh-client recovery on a provisioned node.
import assert from "node:assert/strict";
import test from "node:test";
import { RpcClient } from "../../dist/node/index.js";
import { OutcomeKnowledge } from "../../dist/management.js";
import { currentProfile, CommandOutcome } from "../../dist/transactions.js";
function required(name) { const value = process.env[name]; assert.ok(value, `missing fixture field: ${name}`); return value; }
function bytes(value) { assert.match(value, /^(?:[0-9a-f]{2})+$/); return Buffer.from(value, "hex"); }
test("lost rejection response preserves unknown outcome and explicit recovery", { skip: process.env.LSF_401_LIVE !== "1" }, async () => {
  const tenant = required("LSF_401_TENANT"), key = "typescript-sdk-lost-rejection";
  const command = { namespace: { tenant, namespace: required("LSF_401_NAMESPACE"), incarnation: required("LSF_401_INCARNATION") }, operation: "update", clientKey: key };
  const client = new RpcClient({ endpoint: `http://${required("LSF_401_ENDPOINT")}`, tenant, credential: Buffer.from(required("LSF_401_TOKEN")) });
  try {
    const mode = required("LSF_401_MODE");
    if (mode === "recover") {
      const value = (await client.lookupCommand({ profile: currentProfile(), command, authorizationPublication: { tenant, id: required("LSF_401_PUBLICATION") } })).value.command;
      assert.ok(value && value.outcome === CommandOutcome.Rejected && value.metadataDurable && !value.applicationStateCommitted && !value.commit && value.businessRejection);
      assert.equal(value.commandId, required("LSF_401_ORIGINAL_ID")); assert.equal(value.attemptId, required("LSF_401_ORIGINAL_ATTEMPT"));
      assert.deepEqual(Buffer.from(value.fingerprintSha256), bytes(required("LSF_401_ORIGINAL_FINGERPRINT")));
      assert.deepEqual(Buffer.from(value.businessRejection.code), bytes(required("LSF_401_REJECTION_CODE"))); assert.deepEqual(Buffer.from(value.businessRejection.payload), bytes(required("LSF_401_REJECTION_PAYLOAD")));
      console.log("LOST_REJECTION_RECOVERED");
    } else {
      assert.ok(mode === "invoke" || mode === "conflict");
      const request = { profile: currentProfile(), command, invocation: { activationId: key, target: { tenant, service: "examples/transaction-java-aggregate", contract: "examples:transactional-aggregate/api@1.0.0", function: "update", route: "transaction-java-aggregate" },
        payload: Buffer.from(mode === "conflict" ? '[{"delta":2,"reject":true}]' : '[{"delta":1,"reject":true}]'), mediaType: "application/vnd.latent.wit-values.v1+json", priority: 0, metadata: {},
        budget: { cpuFuel: 1000000000n, memoryBytes: 67108864n, childCalls: 0, outboundRequests: 0, stateReadBytes: 4194304n, stateWriteBytes: 2097152n, blobReadBytes: 0n, blobWriteBytes: 0n, logBytes: 0n, effectCount: 1, wallTimeLimitMillis: 120000n } }, inputFormat: "lsf-wit-values-v1", expectedVersions: [{ key: Buffer.from("aggregate/count"), version: bytes(required("LSF_401_EXPECTED_VERSION_HEX")) }] };
      let failure;
      try { await client.invokeCommand(request); assert.fail("response-blocked call unexpectedly succeeded"); } catch (error) { failure = error?.failure; }
      assert.ok(failure); assert.equal(failure.dispatched, true); assert.equal(failure.outcome, OutcomeKnowledge.Unknown);
      assert.equal(failure.transactionIdentity?.command?.clientKey, key); assert.equal(failure.observedTransaction, undefined);
      if (mode === "conflict") { assert.equal(failure.grpcStatus, 6); console.log("CHANGED_INPUT_CONFLICT"); }
      else console.log("LOST_REJECTION_UNKNOWN");
    }
  } finally {
    await client.shutdown(); const usage = client.usage();
    assert.equal(usage.activeCalls, 0); assert.equal(usage.reservedMessageBytes, 0); assert.equal(usage.sessions, 0); assert.equal(usage.sockets, 0); assert.equal(usage.closed, true);
  }
});
