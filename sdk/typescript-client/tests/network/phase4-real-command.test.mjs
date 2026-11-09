// Explicit live command probe; caller provisions a separate signed node.
import assert from "node:assert/strict";
import test from "node:test";
import { RpcClient } from "../../dist/node/index.js";
import { currentProfile, CommandOutcome } from "../../dist/transactions.js";
function required(name) {
  const value = process.env[name];
  assert.ok(value, `missing live fixture field: ${name}`);
  return value;
}
test("version-fenced command commits through the real Node client and retires", { skip: process.env.LSF_401_LIVE !== "1" }, async () => {
  const tenant = required("LSF_401_TENANT");
  const version = required("LSF_401_EXPECTED_VERSION_HEX");
  assert.match(version, /^(?:[0-9a-f]{2})+$/);
  const client = new RpcClient({ endpoint: `http://${required("LSF_401_ENDPOINT")}`, tenant,
    credential: Buffer.from(required("LSF_401_TOKEN")) });
  try {
    const request = { profile: currentProfile(), command: { namespace: { tenant, namespace: required("LSF_401_NAMESPACE"),
      incarnation: required("LSF_401_INCARNATION") }, operation: "update", clientKey: "typescript-sdk-direct-command" },
      invocation: { activationId: "typescript-sdk-direct-command", target: { tenant, service: "examples/transaction-java-aggregate",
        contract: "examples:transactional-aggregate/api@1.0.0", function: "update", route: "transaction-java-aggregate" },
        payload: Buffer.from('[{"delta":1,"reject":false}]'), mediaType: "application/vnd.latent.wit-values.v1+json", priority: 0,
        metadata: {}, budget: { cpuFuel: 1000000000n, memoryBytes: 67108864n, childCalls: 0, outboundRequests: 0,
          stateReadBytes: 4194304n, stateWriteBytes: 2097152n, blobReadBytes: 0n, blobWriteBytes: 0n, logBytes: 0n,
          effectCount: 1, wallTimeLimitMillis: 120000n } }, inputFormat: "lsf-wit-values-v1",
      expectedVersions: [{ key: Buffer.from("aggregate/count"), version: Buffer.from(version, "hex") }] };
    let result;
    try { result = await client.invokeCommand(request); }
    catch (error) {
      const failure = error?.failure;
      console.error("DIAGNOSTIC", JSON.stringify({ category: failure?.category, outcome: failure?.outcome,
        dispatched: failure?.dispatched, grpcStatus: failure?.grpcStatus, platformCode: failure?.platformError?.code }));
      try {
        const recovered = (await client.lookupCommand({ profile: currentProfile(), command: request.command,
          authorizationPublication: { tenant, id: required("LSF_401_PUBLICATION") } })).value.command;
        console.error("RECOVERY", JSON.stringify({ outcome: recovered?.outcome, commandId: recovered?.commandId,
          attemptId: recovered?.attemptId, metadataDurable: recovered?.metadataDurable,
          applicationStateCommitted: recovered?.applicationStateCommitted, effectCount: recovered?.commit?.effectIds.length }));
      } catch (recovery) { console.error("RECOVERY_FAILED", JSON.stringify({ category: recovery?.failure?.category, dispatched: recovery?.failure?.dispatched })); }
      throw error;
    }
    const command = result.value.command;
    assert.ok(command && command.outcome === CommandOutcome.Committed && command.metadataDurable
      && command.applicationStateCommitted && command.commit);
    assert.equal(command.commit.effectIds.length, 1);
    console.log(`RESULT ${command.commandId} ${command.attemptId} ${command.commit.effectIds[0]}`);
  } finally {
    await client.shutdown();
    const usage = client.usage();
    assert.equal(usage.activeCalls, 0); assert.equal(usage.reservedMessageBytes, 0);
    assert.equal(usage.sessions, 0); assert.equal(usage.sockets, 0); assert.equal(usage.closed, true);
  }
});
