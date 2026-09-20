import { access, writeFile, rename } from "node:fs/promises";
import { join } from "node:path";
import { setTimeout as delay } from "node:timers/promises";
import { performance } from "node:perf_hooks";
import { isDeepStrictEqual } from "node:util";
import { RpcClient, RpcError } from "../dist/node/index.js";
import { FailureCategory as Category, OutcomeKnowledge as Knowledge } from "../dist/management.js";
import { protectedFile } from "../examples/protected-file.mjs";
import { guestU64, providerRequest } from "../examples/provider-request.mjs";

let stage = "configuration";
function check(condition, reason) { if (!condition) throw new Error(reason); }

async function rejected(promise, predicate, reason) {
  const result = await promise.then((value) => ({ value }), (error) => ({ error }));
  check(result.error instanceof RpcError && predicate(result.error.failure), reason);
  return result.error.failure;
}

function load() {
  check(process.argv.length === 4 && process.argv[2] === "--config", "configuration-arguments");
  const bytes = protectedFile(process.argv[3], 16384);
  const config = JSON.parse(bytes.toString("utf8"));
  check(config.schemaVersion === "latent.sdk.provider.workflow.input.v1" && config.language === "typescript"
    && config.tenant === "tests" && typeof config.policyDocument === "string" && config.policyDocument.length <= 1024,
  "configuration-profile");
  const credential = protectedFile(config.credentialFile, 256);
  return { config, credential };
}

async function rendezvous(config, prefix, token, timeout = 4000) {
  const deadline = performance.now() + timeout;
  const path = join(config.controlDirectory, `${prefix}-${token}`);
  while (performance.now() < deadline) {
    try { await access(path); return; } catch (error) { if (error.code !== "ENOENT") throw error; }
    await delay(2);
  }
  throw new Error("provider-rendezvous-expired");
}

async function setMode(config, value) {
  const temporary = join(config.controlDirectory, "mode.tmp");
  await writeFile(temporary, value, { mode: 0o600, flag: "wx" });
  await rename(temporary, join(config.controlDirectory, "mode"));
}

async function terminal(client, activationId) {
  const deadline = performance.now() + 4000;
  while (performance.now() < deadline) {
    const result = await client.getActivation({ activationId }, { timeoutMillis: 1000n });
    check(result.value.activationId === activationId, "retained-identity");
    if (result.value.terminalState !== undefined) return result;
    await delay(2);
  }
  throw new Error("retained-terminal-expired");
}

async function management(client, config, assertions) {
  stage = "policy-first-page";
  const first = await client.listPolicies({ recordKind: 1, page: { pageSize: 1 } });
  check(first.value.policies.length === 1 && first.value.page.nextPageToken, "bounded-first-page");
  stage = "policy-next-page";
  const second = await client.listPolicies({ recordKind: 1, page: { pageSize: 1, pageToken: first.value.page.nextPageToken } });
  check(second.value.policies.length === 1 && second.value.policies[0].id !== first.value.policies[0].id, "bounded-next-page");
  assertions.boundedPages = true;
  stage = "provider-inspection";
  const providers = await client.listCapabilities({ deploymentId: config.targets.http.route, page: { pageSize: 1 }, includeNodeUsage: false });
  check(providers.value.capabilities.length === 1 && providers.value.capabilities[0].contract === "latent:http/client@0.2.0", "provider-inspection");
  assertions.providerInspection = true;
  const operationId = "typescript-policy-create";
  const id = "typescript-example-policy";
  const original = { operationId, expectedGeneration: 0n, policy: { id, metadata: { name: id, tenant: config.tenant, labels: {}, annotations: {} },
    document: config.policyDocument, generation: 0n, language: "lsf-capability-policy-v1", recordKind: 1, contentDigest: "", revoked: false } };
  stage = "policy-mutation";
  const created = await client.applyPolicy(original);
  check(created.metadata.auditAck === undefined && created.metadata.auditStatus === undefined
    && created.metadata.auditAttemptSequence === undefined, "policy-audit-absence");
  check(created.value.receipt.operationId === operationId, "mutation-receipt-identity");
  stage = "policy-inspection";
  const policy = await client.getPolicy({ id, recordKind: 1 });
  check(policy.value.policy.generation === created.value.receipt.generation, "policy-inspection");
  // lsf-example-begin: management
  stage = "operation-recovery";
  const receipt = await client.getPolicyOperation({ operationId });
  check(isDeepStrictEqual(receipt.value.receipt, created.value.receipt), "operation-recovery");
  // lsf-example-end: management
  stage = "operation-absence";
  const absent = await client.getPolicyOperation({ operationId: "typescript-unknown-operation" });
  check(absent.value.receipt === undefined && absent.metadata.outcome === Knowledge.Unknown, "absent-receipt-is-unknown");
  assertions.mutationReceipt = true;
  stage = "policy-replay";
  const replay = await client.applyPolicy(original);
  check(isDeepStrictEqual(replay.value.receipt, created.value.receipt), "exact-manual-replay");
  assertions.exactReplay = true;
  stage = "policy-conflict";
  await rejected(client.applyPolicy({ ...original, operationId: "typescript-stale-precondition" }),
    (failure) => failure.category === Category.Rpc && failure.outcome === Knowledge.Observed, "precondition-conflict");
  assertions.preconditionConflict = true;
  return { operationId, auditAttempt: null };
}

async function held(client, config, kind, assertions, activationIds) {
  stage = kind;
  const activationId = `typescript-${kind}`;
  const token = `hold-${activationId}`;
  await setMode(config, token);
  const controller = new AbortController();
  const pending = client.invoke(providerRequest(config.targets.http, config.tenant, activationId, "http", config.upstreamUrl),
    { signal: controller.signal, timeoutMillis: kind === "deadline" ? 500n : 3000n })
    .then((value) => ({ value }), (error) => ({ error }));
  await rendezvous(config, "started", token);
  activationIds.push(activationId);
  const running = await client.getActivation({ activationId });
  check(running.value.activationId === activationId && running.value.terminalState === undefined, "held-activation-not-running");
  if (kind === "local-cancel") {
    // lsf-example-begin: cancel
    controller.abort();
    const result = await pending;
    check(result.error instanceof RpcError && result.error.failure.category === Category.LocalCancelled
      && result.error.failure.identity.activationId === activationId && result.error.failure.outcome === Knowledge.Unknown, "local-cancellation-semantics");
    const cancelled = await client.cancel({ activationId, reason: "explicit recovery" });
    check([1, 2].includes(cancelled.value.disposition), "lost-response-explicit-cancel");
    // lsf-example-end: cancel
    assertions.localCancellation = true;
    assertions.lostResponseStatus = true;
  } else if (kind === "explicit-cancel") {
    const cancelled = await client.cancel({ activationId, reason: "explicit server cancellation" });
    check(cancelled.value.disposition === 1, "explicit-cancel-not-accepted");
    const result = await pending;
    check(result.value?.value.platformFailure?.code === "cancelled"
      || result.error instanceof RpcError && [1, 4].includes(result.error.failure.grpcStatus), "explicit-cancel-result");
    assertions.explicitCancellation = true;
  } else if (kind === "deadline") {
    const result = await pending;
    check(result.error instanceof RpcError && result.error.failure.category === Category.Deadline
      && result.error.failure.identity.activationId === activationId, "absolute-deadline-result");
    assertions.absoluteDeadline = true;
  } else {
    await Promise.all([client.shutdown(), client.shutdown()]);
    const result = await pending;
    check(result.error instanceof RpcError && result.error.failure.category === Category.LocalCancelled, "shutdown-outstanding-result");
    const usage = client.usage();
    check(usage.activeCalls === 0 && usage.reservedMessageBytes === 0 && usage.sessions === 0 && usage.sockets === 0 && usage.closed,
      "physical-client-retirement");
    assertions.shutdownOutstanding = true;
    assertions.clientOwnersReaped = true;
  }
  await rendezvous(config, "closed", token);
  await setMode(config, "reply");
  if (kind !== "shutdown") await terminal(client, activationId);
}

async function run() {
  const { config, credential } = load();
  const options = { endpoint: config.endpoint, tenant: config.tenant, credential, limits: { rpcTimeoutMillis: 5000 } };
  const client = new RpcClient(options);
  const recovery = new RpcClient(options);
  const foreign = new RpcClient({ ...options, tenant: "foreign" });
  const denied = new RpcClient({ ...options, credential: Buffer.from("LSF-PUBLIC-WRONG-NODE-TOKEN-TEST-ONLY") });
  const small = new RpcClient({ ...options, limits: { ...options.limits, maximumResponseBytes: 64 } });
  credential.fill(0);
  const owners = [client, recovery, foreign, denied, small];
  const assertions = {};
  const activationIds = [];
  const request = (name, suffix = name, functionName) => providerRequest(config.targets[name], config.tenant,
    `typescript-${suffix}`, name, config.upstreamUrl, functionName);
  try {
    // lsf-example-begin: invoke
    stage = "http-invocation";
    check(guestU64(await client.invoke(request("http"))) === "2201", "http-guest-result");
    activationIds.push("typescript-http"); assertions.httpGuest = true;
    stage = "blob-invocation";
    check(guestU64(await client.invoke(request("blob"))) === "4", "blob-guest-result");
    activationIds.push("typescript-blob"); assertions.blobGuest = true;
    // lsf-example-end: invoke
    stage = "declared-invocation";
    const declared = await client.invoke(request("callee", "declared", "fail"));
    check(declared.value.declaredError !== undefined, "declared-error-variant");
    activationIds.push("typescript-declared"); assertions.declaredError = true;
    stage = "platform-invocation";
    const exhausted = request("callee", "platform", "spin"); exhausted.budget.cpuFuel = 1000n;
    check((await client.invoke(exhausted)).value.platformFailure !== undefined, "platform-failure-variant");
    activationIds.push("typescript-platform"); assertions.platformFailure = true;
    stage = "tenant-denial";
    const wrongTenant = request("http", "wrong-tenant"); wrongTenant.target.tenant = "foreign";
    await rejected(foreign.invoke(wrongTenant), (failure) => failure.grpcStatus === 7, "wrong-tenant-not-denied"); assertions.wrongTenant = true;
    stage = "credential-denial";
    await rejected(denied.invoke(request("http", "wrong-auth")), (failure) => failure.grpcStatus === 16, "wrong-credential-not-denied"); assertions.wrongCredential = true;
    stage = "response-limit";
    await rejected(small.invoke(request("http", "limited")), (failure) => failure.category === Category.Limit && failure.identity.activationId === "typescript-limited", "response-limit-not-enforced");
    activationIds.push("typescript-limited"); assertions.responseLimit = true;
    await terminal(client, "typescript-limited");
    const mutation = await management(client, config, assertions);
    for (const kind of ["local-cancel", "explicit-cancel", "deadline", "shutdown"]) await held(client, config, kind, assertions, activationIds);
    await terminal(recovery, "typescript-shutdown");
    for (const owner of owners) await owner.shutdown();
    check(owners.every((owner) => owner.usage().sockets === 0 && owner.usage().activeCalls === 0 && owner.usage().sessions === 0), "all-client-owners-retired");
    return { schemaVersion: "latent.sdk.provider.workflow.result.v1", language: "typescript", assertions, activationIds,
      ...mutation, transport: "numeric-loopback-http2-protobuf-v1" };
  } finally { for (const owner of owners) await owner.shutdown(); }
}

run().then((result) => process.stdout.write(JSON.stringify(result) + "\n")).catch((error) => {
  const reason = /^[a-z-]{1,80}$/.test(error.message) ? error.message : "rpc-or-runtime";
  const failure = error instanceof RpcError ? { category: error.failure.category, grpcStatus: error.failure.grpcStatus } : {};
  process.stderr.write(JSON.stringify({ stage, reason, ...failure }) + "\n");
  process.exitCode = 1;
});
