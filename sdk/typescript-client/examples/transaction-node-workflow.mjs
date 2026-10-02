// Actual Node SDK participant. This program installs no namespace or authority.
import { constants } from "node:fs";
import { open, lstat, writeFile } from "node:fs/promises";
import { resolve, join } from "node:path";
import { createInterface } from "node:readline";
import { RpcClient, RpcError } from "../dist/node/index.js";
import { decode, encode } from "../dist/node/protocol/codec.js";
import { method, transactionRegistry } from "../dist/node/protocol/schema.js";

const maximum = 2 * 1024 * 1024;
const methods = Object.freeze({
  "invoke_command": "invokeCommand",
  "query": "query",
  "lookup_command": "lookupCommand",
  "lookup_commit": "lookupCommit",
  "get_effect": "getEffect",
  "list_effect_history": "listEffectHistory",
  "cancel_command": "cancelCommand",
  "mutate_namespace": "mutateNamespace",
  "inspect_namespace": "inspectNamespace",
  "select_entity": "selectEntity",
  "mutate_state": "mutateState",
  "plan_effect_mutation": "planEffectMutation",
  "get_state_operation_receipt": "getStateOperationReceipt",
  "inspect_dispatcher": "inspectDispatcher",
  "control_dispatcher": "controlDispatcher",
  "get_dispatcher_operation": "getDispatcherOperation"
});
const observationTypes = { command: "latent.transaction.v1.CommandInspection", state: "latent.control.v1.StateOperationReceipt",
  namespace: "latent.control.v1.NamespaceOperationReceipt", effect: "latent.transaction.v1.EffectReceipt",
  dispatcher: "latent.control.v1.DispatcherOperationReceipt", effectPlan: "latent.control.v1.EffectManagementPlan" };
function require(value) { if (!value) throw new Error("transaction-node-fixture-input"); }
async function read(path, limit) {
  const file = await open(path, constants.O_RDONLY | constants.O_NOFOLLOW);
  try {
    const metadata = await file.stat();
    require(metadata.isFile() && metadata.uid === process.getuid() && (metadata.mode & 0o077) === 0 && metadata.size <= limit);
    const bytes = Buffer.alloc(metadata.size + 1);
    let count = 0;
    while (count < bytes.length) {
      const { bytesRead } = await file.read(bytes, count, bytes.length - count, count);
      if (bytesRead === 0) break;
      count += bytesRead;
    }
    require(count === metadata.size);
    return bytes.subarray(0, count);
  } finally { await file.close(); }
}
async function write(path, value) {
  require(value.length <= maximum);
  await writeFile(path, value, { flag: "wx", mode: 0o600 });
}
async function observation(directory, id, observed) {
  if (observed === undefined) return;
  const schema = transactionRegistry.getMessage(observationTypes[observed.kind]);
  require(schema);
  const value = observed.kind === "command" ? observed.command : observed.kind === "effectPlan" ? observed.plan : observed.receipt;
  await write(join(directory, `${id}.${observed.kind}.pb`), encode(schema, value, maximum, true));
}
async function main() {
  const [flag, endpoint, tenant, credentialFile, work, ...extra] = process.argv.slice(2);
  require(flag === "--node-fixture" && extra.length === 0 && process.platform === "linux" && work);
  const directory = resolve(work);
  const metadata = await lstat(directory);
  require(metadata.isDirectory() && !metadata.isSymbolicLink() && metadata.uid === process.getuid() && (metadata.mode & 0o077) === 0);
  const credential = await read(credentialFile, 256);
  const client = new RpcClient({ endpoint, tenant, credential, limits: { maximumCalls: 4,
    maximumRequestBytes: maximum, maximumResponseBytes: maximum, rpcTimeoutMillis: 5000 } });
  credential.fill(0);
  const input = createInterface({ input: process.stdin, crlfDelay: Infinity });
  const deadline = performance.now() + 120000;
  const lifetime = new AbortController();
  const expiry = setTimeout(() => { lifetime.abort(); input.close(); process.stdin.destroy(); }, 120000);
  const used = new Set();
  try {
    console.log("ready");
    for await (const line of input) {
      if (line === "close") break;
      const values = line.split(" ");
      const [operation, id, timeoutText, cancelText] = values;
      require(line.length <= 192 && values.length === 4 && Object.hasOwn(methods, operation) && /^[A-Za-z0-9_-]{1,64}$/.test(id)
        && /^([1-9][0-9]{0,3})$/.test(timeoutText) && /^(-1|0|[1-9][0-9]{0,3})$/.test(cancelText)
        && used.size < 32 && !used.has(id) && performance.now() < deadline);
      used.add(id);
      const timeout = Number(timeoutText), cancel = Number(cancelText);
      require(timeout <= 5000 && cancel <= 5000);
      const descriptor = method(methods[operation]);
      const request = decode(descriptor.input, await read(join(directory, `${id}.request.pb`), maximum), maximum, true);
      const local = new AbortController();
      const signal = AbortSignal.any([lifetime.signal, local.signal]);
      if (cancel === 0) local.abort();
      const timer = cancel > 0 ? setTimeout(() => local.abort(), cancel) : undefined;
      let result;
      try {
        const response = await client[methods[operation]](request, { timeoutMillis: BigInt(Math.max(1, Math.min(timeout, Math.floor(deadline - performance.now())))), signal });
        await write(join(directory, `${id}.response.pb`), encode(descriptor.output, response.value, maximum, true));
        await observation(directory, id, response.metadata.observedTransaction);
        result = { status: "response" };
      } catch (error) {
        if (!(error instanceof RpcError)) throw error;
        await observation(directory, id, error.failure.observedTransaction);
        result = { status: "failure", failureCategory: error.failure.category, grpcStatus: error.failure.grpcStatus ?? null,
          dispatched: error.failure.dispatched };
      } finally { clearTimeout(timer); }
      await write(join(directory, `${id}.result.json`), Buffer.from(JSON.stringify(result)));
      console.log(`done ${id}`);
    }
    require(!lifetime.signal.aborted);
  } finally {
    clearTimeout(expiry); input.close();
    let shutdown = false;
    try { await client.shutdown(5000); shutdown = true; } finally {
      const usage = client.usage();
      const clean = shutdown && usage.closed && usage.activeCalls === 0 && usage.reservedMessageBytes === 0 && usage.sessions === 0 && usage.sockets === 0;
      await write(join(directory, "cleanup.json"), Buffer.from(JSON.stringify({ schemaVersion: "latent.sdk.transaction.node.cleanup.v1", clean, ...usage })));
      require(clean);
    }
  }
}
main().catch(() => { console.error("transaction-node-workflow-failed"); process.exitCode = 1; });
