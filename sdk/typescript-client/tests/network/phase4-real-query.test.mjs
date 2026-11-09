// Explicit fresh query after a committed command on a provisioned node.
import assert from "node:assert/strict";
import test from "node:test";
import { RpcClient } from "../../dist/node/index.js";
import { currentProfile } from "../../dist/transactions.js";
function required(name) { const value = process.env[name]; assert.ok(value, `missing fixture field: ${name}`); return value; }
test("fresh query observes the committed view without a command receipt", { skip: process.env.LSF_401_LIVE !== "1" }, async () => {
  const tenant = required("LSF_401_TENANT"), minimum = Buffer.from(required("LSF_401_QUERY_MINIMUM_HEX"), "hex");
  const expected = Buffer.from(process.env.LSF_401_QUERY_EXPECTED_HEX || required("LSF_401_QUERY_MINIMUM_HEX"), "hex");
  assert.ok(minimum.length && expected.length);
  const namespace = { tenant, namespace: required("LSF_401_NAMESPACE"), incarnation: required("LSF_401_INCARNATION") };
  const client = new RpcClient({ endpoint: `http://${required("LSF_401_ENDPOINT")}`, tenant, credential: Buffer.from(required("LSF_401_TOKEN")) });
  try {
    for (let i = 0; i < 3; i++) {
      const invocation = { activationId: `typescript-sdk-fresh-query-${i}`, target: { tenant, service: "examples/transaction-java-aggregate", contract: "examples:transactional-aggregate/api@1.0.0", function: "query", route: "transaction-java-aggregate" },
        payload: Buffer.from("[]"), mediaType: "application/vnd.latent.wit-values.v1+json", priority: 0, metadata: {},
        budget: { cpuFuel: 1000000000n, memoryBytes: 67108864n, childCalls: 0, outboundRequests: 0, stateReadBytes: 4194304n, stateWriteBytes: 0n, blobReadBytes: 0n, blobWriteBytes: 0n, logBytes: 0n, effectCount: 0, wallTimeLimitMillis: 120000n } };
      const response = await client.query({ profile: currentProfile(), namespace, minimumViewVersion: minimum, invocation });
      assert.equal(response.metadata.observedTransaction, undefined);
      const value = response.value; assert.ok(value.view && value.view.namespace && value.source && value.invocation?.success);
      assert.deepEqual(value.view.namespace, namespace); assert.deepEqual(Buffer.from(value.view.version), expected);
      assert.equal(value.invocation.success.committedStateVersion, undefined); assert.equal(value.invocation.success.effectIds.length, 0);
      const frame = JSON.parse(Buffer.from(value.invocation.success.payload).toString("utf8"));
      assert.equal(frame.length, 1); assert.equal(frame[0].ok.count, "2"); assert.deepEqual(Buffer.from(frame[0].ok["view-version"]), expected);
    }
    console.log("FRESH_QUERY_AFTER_COMMIT");
  } finally {
    await client.shutdown(); const usage = client.usage();
    assert.equal(usage.activeCalls, 0); assert.equal(usage.sessions, 0); assert.equal(usage.sockets, 0); assert.equal(usage.closed, true);
  }
});
