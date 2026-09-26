import { RpcClient, RpcError } from "../dist/node/index.js";
import { protectedFile } from "./protected-file.mjs";
import { providerRequest, guestU64 } from "./provider-request.mjs";

async function main() {
  const args = process.argv.slice(2);
  const [endpoint, tenant, credentialFile, activationId, mode, service, route, url] = args;
  if (!args.every((value) => value.length <= 4096) || !["http", "blob", "status", "cancel"].includes(mode)
    || args.length !== ({ http: 8, blob: 7, status: 5, cancel: 5 })[mode]) throw new Error("invalid-example-arguments");
  const credential = protectedFile(credentialFile, 256);
  let client;
  try { client = new RpcClient({ endpoint, tenant, credential, limits: { rpcTimeoutMillis: 5000 } }); } finally { credential.fill(0); }
  let result;
  try {
    if (mode === "status") {
      const reply = await client.getActivation({ activationId });
      result = { outcome: "status", phase: reply.value.phase, terminalState: reply.value.terminalState };
    } else if (mode === "cancel") {
      const reply = await client.cancel({ activationId, reason: "explicit example request" });
      result = { outcome: "cancel", disposition: reply.value.disposition };
    } else {
      const target = { service, route, contract: mode === "http" ? "tests:http/api@1.0.0" : "tests:local-blobs/api@1.0.0", function: "run" };
      const reply = await client.invoke(providerRequest(target, tenant, activationId, mode, url));
      result = reply.value.success ? { outcome: "succeeded", guestResult: guestU64(reply), activationId: reply.value.activationId }
        : { outcome: reply.value.declaredError ? "declared-error" : "platform-failure" };
    }
  } catch (error) {
    if (!(error instanceof RpcError)) throw error;
    result = { outcome: "rpc-failure", category: error.failure.category, grpcStatus: error.failure.grpcStatus,
      dispatched: error.failure.dispatched, outcomeKnowledge: error.failure.outcome, identity: error.failure.identity };
  } finally { await client.shutdown(); }
  process.stdout.write(JSON.stringify({ schemaVersion: "latent.node.provider-client.v1", ...result, clientOwnersReaped: true }) + "\n");
}

main().catch(() => { process.stderr.write("provider-client-failed\n"); process.exitCode = 1; });
