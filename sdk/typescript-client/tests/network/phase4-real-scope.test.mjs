// Explicit caller-scope refusal on a separately provisioned node.
import assert from "node:assert/strict";
import test from "node:test";
import { RpcClient } from "../../dist/node/index.js";
import { currentProfile } from "../../dist/transactions.js";
function required(name) { const value = process.env[name]; assert.ok(value, `missing fixture field: ${name}`); return value; }
test("different caller cannot recover original command", { skip: process.env.LSF_401_LIVE !== "1" }, async () => {
  const tenant = required("LSF_401_TENANT");
  const client = new RpcClient({ endpoint: `http://${required("LSF_401_ENDPOINT")}`, tenant, credential: Buffer.from(required("LSF_401_SCOPE_TOKEN")) });
  try {
    let failure;
    try { await client.lookupCommand({ profile: currentProfile(), command: { namespace: { tenant, namespace: required("LSF_401_NAMESPACE"), incarnation: required("LSF_401_INCARNATION") }, operation: "update", clientKey: required("LSF_401_COMMAND_KEY") }, authorizationPublication: { tenant, id: required("LSF_401_PUBLICATION") } }); }
    catch (error) { failure = error?.failure; }
    assert.ok(failure); assert.equal(failure.grpcStatus, 7); assert.equal(failure.observedTransaction, undefined);
    console.log("SCOPE_REFUSED grpc=7");
  } finally { await client.shutdown(); const usage = client.usage(); assert.equal(usage.activeCalls, 0); assert.equal(usage.reservedMessageBytes, 0); assert.equal(usage.sessions, 0); assert.equal(usage.sockets, 0); assert.equal(usage.closed, true); }
});
