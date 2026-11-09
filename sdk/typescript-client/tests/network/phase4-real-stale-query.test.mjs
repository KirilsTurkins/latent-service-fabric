// Original expected versions must survive a stale application edit.
import assert from "node:assert/strict";
import test from "node:test";
import { RpcClient } from "../../dist/node/index.js";
import { currentProfile, CommandOutcome } from "../../dist/transactions.js";
function required(name) { const value=process.env[name]; assert.ok(value, `missing fixture field: ${name}`); return value; }
test("stale edit retains the original expected version", { skip: process.env.LSF_401_LIVE !== "1" }, async () => {
  const tenant=required("LSF_401_TENANT"), key="typescript-sdk-stale-edit";
  const version=Buffer.from(required("LSF_401_EXPECTED_VERSION_HEX"),"hex"); assert.ok(version.length);
  const command={namespace:{tenant,namespace:required("LSF_401_NAMESPACE"),incarnation:required("LSF_401_INCARNATION")},operation:"update",clientKey:key};
  const client=new RpcClient({endpoint:`http://${required("LSF_401_ENDPOINT")}`,tenant,credential:Buffer.from(required("LSF_401_TOKEN"))});
  try {
    const request={profile:currentProfile(),command,invocation:{activationId:key,target:{tenant,service:"examples/transaction-java-aggregate",contract:"examples:transactional-aggregate/api@1.0.0",function:"update",route:"transaction-java-aggregate"},payload:Buffer.from('[{"delta":1,"reject":false}]'),mediaType:"application/vnd.latent.wit-values.v1+json",priority:0,metadata:{},budget:{cpuFuel:1000000000n,memoryBytes:67108864n,childCalls:0,outboundRequests:0,stateReadBytes:4194304n,stateWriteBytes:2097152n,blobReadBytes:0n,blobWriteBytes:0n,logBytes:0n,effectCount:1,wallTimeLimitMillis:120000n}},inputFormat:"lsf-wit-values-v1",expectedVersions:[{key:Buffer.from("aggregate/count"),version}]};
    const response=await client.invokeCommand(request);
    assert.deepEqual(Buffer.from(response.metadata.transactionIdentity.expectedVersions[0].version),version);
    const result=response.value.command; assert.ok(result); assert.equal(result.outcome,CommandOutcome.Aborted);
    assert.equal(result.metadataDurable,true); assert.equal(result.applicationStateCommitted,false);
    assert.equal(result.commit,undefined); assert.ok(result.provenAbort);
    console.log("TYPESCRIPT_STALE_EDIT_ABORTED");
  } finally { await client.shutdown(); const usage=client.usage(); assert.equal(usage.activeCalls,0); assert.equal(usage.sockets,0); assert.equal(usage.sessions,0); assert.equal(usage.closed,true); }
});
