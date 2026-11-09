// Explicitly provisioned separate-node probe; ordinary peer tests do not satisfy it.
import assert from "node:assert/strict";
import test from "node:test";
import { RpcClient } from "../../dist/node/index.js";
import { currentProfile, CommandOutcome } from "../../dist/transactions.js";

function required(name) {
  const value = process.env[name];
  assert.ok(value, `required live-node fixture field missing: ${name}`);
  return value;
}

test("committed command lookup uses the real Node client and retires", { skip: process.env.LSF_401_LIVE !== "1" }, async () => {
  const tenant = required("LSF_401_TENANT");
  const client = new RpcClient({ endpoint: `http://${required("LSF_401_ENDPOINT")}`, tenant,
    credential: Buffer.from(required("LSF_401_TOKEN")) });
  try {
    const key = required("LSF_401_COMMAND_KEY");
    const request = { profile: currentProfile(), command: { namespace: { tenant,
      namespace: required("LSF_401_NAMESPACE"), incarnation: required("LSF_401_INCARNATION") },
      operation: required("LSF_401_OPERATION"), clientKey: key },
      authorizationPublication: { tenant, id: required("LSF_401_PUBLICATION") } };
    const first = (await client.lookupCommand(request)).value.command;
    const second = (await client.lookupCommand(request)).value.command;
    assert.ok(first && second);
    assert.equal(first.commandId, required("LSF_401_COMMAND_ID"));
    assert.equal(first.attemptId, required("LSF_401_ATTEMPT_ID"));
    assert.equal(first.key.clientKey, key);
    assert.equal(first.outcome, CommandOutcome.Committed);
    assert.ok(first.metadataDurable && first.applicationStateCommitted && first.commit);
    for (const field of ["commandId", "attemptId", "key", "fingerprintSha256", "outcome", "source", "commit"])
      assert.deepEqual(first[field], second[field]);
  } finally {
    await client.shutdown();
    const usage = client.usage();
    assert.equal(usage.activeCalls, 0);
    assert.equal(usage.reservedMessageBytes, 0);
    assert.equal(usage.sessions, 0);
    assert.equal(usage.sockets, 0);
    assert.equal(usage.closed, true);
  }
});

