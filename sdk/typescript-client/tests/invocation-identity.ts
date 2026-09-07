import type { InvokeRequest, LatentClient } from "../src/index.js";
import { FakeClient, ServerRejection, TransportFailure } from "./fake-client.js";

function check(value: unknown, message: string): asserts value {
  if (!value) throw new Error(message);
}

type Identity = Pick<InvokeRequest, "activationId" | "rootActivationId" | "parentActivationId">;

function request(identity: Identity = {}): InvokeRequest {
  return {
    target: { tenant: "tenant", service: "echo", contract: "example:echo/api@1.0.0", function: "echo" },
    payload: new Uint8Array([1]), mediaType: "application/octet-stream",
    options: { priority: 0, idempotencyKey: "separate-key", metadata: {}, budget: {
      cpuFuel: 1n, memoryBytes: 1n, childCalls: 0, outboundRequests: 0,
      stateReadBytes: 0n, stateWriteBytes: 0n, blobReadBytes: 0n,
      blobWriteBytes: 0n, logBytes: 0n, effectCount: 0,
    } },
    ...identity,
  };
}

async function pendingCancellation(): Promise<void> {
  const server = new FakeClient();
  const client: LatentClient = server;
  const sent = request({ activationId: "known" });
  let terminal = false;
  const pending = client.invoke(sent).then(outcome => { terminal = true; return outcome; });
  check((await client.getActivation("known")).phase === "running", "status before terminal response");
  check(!terminal, "invoke remains pending while caller knows its ID");
  check(server.lineage("known").root === "known" && server.lineage("known").parent === undefined,
    "server defaults root to effective identity");
  server.failNextCancel = true;
  try {
    await client.cancel("known", "stop");
    throw new Error("transport error must reject");
  } catch (error) {
    check(error instanceof TransportFailure, "transport failure is not a cancel disposition");
  }
  const accepted = await client.cancel("known", "stop");
  check(accepted.disposition === "accepted" && accepted.terminalState === undefined, "accepted disposition");
  check(!terminal, "cancel acknowledgment is not terminal completion");
  server.finish("known");
  const outcome = await pending;
  check(outcome.kind === "platform-failure" && outcome.error.code === "cancelled", "typed terminal cancellation");
  const already = await client.cancel("known", "again");
  check(already.disposition === "already-terminal" && already.terminalState === "cancelled", "terminal disposition/state");
  const missing = await client.cancel("missing", "stop");
  check(missing.disposition === "not-found" && missing.terminalState === undefined, "not-found disposition");
  check(server.requests.length === 1 && server.requests[0] === sent, "identity unchanged and no implicit invoke retry");
}

async function lostResponse(): Promise<void> {
  const server = new FakeClient();
  const client: LatentClient = server;
  const pending = client.invoke(request({ activationId: "recoverable" }));
  server.finish("recoverable", true);
  try {
    await pending;
    throw new Error("lost response must reject");
  } catch (error) {
    check(error instanceof TransportFailure, "lost transport response stays distinct from platform outcome");
  }
  const retained = await client.getActivation("recoverable");
  check(retained.terminalState === "completed" && retained.terminalOutcome?.kind === "success", "recover retained result by known ID");
  check(server.requests.length === 1, "status recovery must not reinvoke");
}

async function optionalIdentity(): Promise<void> {
  const server = new FakeClient();
  const absent = request();
  const pending = server.invoke(absent);
  check(!Object.hasOwn(absent, "activationId") && !Object.hasOwn(absent, "rootActivationId") &&
    !Object.hasOwn(absent, "parentActivationId"), "absence is preserved, not SDK-generated");
  check(server.lineage("server-assigned-1").root === "server-assigned-1" &&
    server.lineage("server-assigned-1").parent === undefined, "fake server root default");
  server.finish("server-assigned-1");
  const assigned = await pending;
  check(assigned.kind === "success" && assigned.response.activationId === "server-assigned-1", "server-assigned response identity");
  const explicit = request({ activationId: "child", rootActivationId: "root", parentActivationId: "parent" });
  const child = server.invoke(explicit);
  check(server.requests[1] === explicit && server.lineage("child").root === "root" &&
    server.lineage("child").parent === "parent", "explicit lineage survives unchanged as claims");
  server.finish("child");
  await child;
  const invalidIdentities: Identity[] = [
    { activationId: "" }, { rootActivationId: "" }, { parentActivationId: "", rootActivationId: "root" },
    { activationId: "orphan", parentActivationId: "parent" },
  ];
  for (const identity of invalidIdentities) {
    const invalid = request(identity);
    try {
      await server.invoke(invalid);
      throw new Error("fake server must reject invalid identity");
    } catch (error) {
      check(error instanceof ServerRejection, "validation belongs to fake server, not SDK coercion");
    }
    check(server.requests.at(-1) === invalid, "present empty and missing root arrive unchanged");
  }
}

let timeout: ReturnType<typeof setTimeout> | undefined;
try {
  await Promise.race([
    (async () => { await pendingCancellation(); await lostResponse(); await optionalIdentity(); })(),
    new Promise<never>((_resolve, reject) => { timeout = setTimeout(() => reject(new Error("semantic fixture timeout")), 5000); }),
  ]);
  console.log("TypeScript invocation identity semantic fixtures passed");
} finally {
  if (timeout !== undefined) clearTimeout(timeout);
}
