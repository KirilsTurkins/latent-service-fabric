import { profile as Profile } from "../src/index.js";

function check(value: unknown, message: string): asserts value {
  if (!value) throw new Error(message);
}

function metadata(identity: Profile.RequestIdentity, outcome: Profile.OutcomeKnowledge = Profile.OutcomeKnowledge.Observed): Profile.ResponseMetadata {
  return { identity, outcome };
}

class FixtureClient implements Profile.ClientProfile {
  applyCalls = 0;
  serverWrites = 0;
  cancelCalls = 0;
  pageCalls = 0;
  waiters = 0;
  receipt?: Profile.CapabilityPolicyOperation;
  policy?: Profile.Policy;

  private response<Response>(value: Response, identity: Profile.RequestIdentity = {}): Promise<Profile.ClientResponse<Response>> {
    return Promise.resolve({ value, metadata: metadata(identity) });
  }

  invoke(request: Profile.InvokeRequest): Promise<Profile.ClientResponse<Profile.InvokeResponse>> {
    const activationId = request.activationId ?? "server-assigned";
    return this.response({ activationId, revisionId: "revision-a", releaseDigest: "component-a", routeGeneration: 1n,
      success: { payload: new Uint8Array(request.payload), mediaType: request.mediaType, effectIds: [], metadata: {} } }, { activationId });
  }

  cancel(request: Profile.CancelRequest): Promise<Profile.ClientResponse<Profile.CancelResponse>> {
    this.cancelCalls++;
    return this.response({ disposition: Profile.CancelDisposition.Accepted }, { activationId: request.activationId });
  }

  getActivation(request: Profile.GetActivationRequest): Promise<Profile.ClientResponse<Profile.ActivationStatus>> {
    return this.response({ activationId: request.activationId, phase: "running", lastUpdatedUnixMillis: 0n, metadata: {} }, { activationId: request.activationId });
  }

  getPolicy(request: Profile.GetPolicyRequest): Promise<Profile.ClientResponse<Profile.GetPolicyResponse>> {
    return this.response(this.policy?.id === request.id ? { policy: structuredClone(this.policy) } : {});
  }

  listPolicies(_request: Profile.ListPoliciesRequest): Promise<Profile.ClientResponse<Profile.ListPoliciesResponse>> {
    this.pageCalls++;
    return this.response({ policies: this.policy ? [structuredClone(this.policy)] : [], catalogGeneration: 1n, page: { nextPageToken: "opaque-next-page" } });
  }

  listCapabilities(request: Profile.ListCapabilitiesRequest): Promise<Profile.ClientResponse<Profile.ListCapabilitiesResponse>> {
    return this.response({ capabilities: [], state: "binding-plan-unavailable", page: {},
      revision: { deploymentId: request.deploymentId, revisionId: "revision-a", componentDigest: "component-a", routeGeneration: 1n, catalogTransaction: 1n } });
  }

  applyPolicy(request: Profile.ApplyPolicyRequest, options: Profile.CallOptions = {}): Promise<Profile.ClientResponse<Profile.ApplyPolicyResponse>> {
    const identity = { operationId: request.operationId };
    if (options.signal?.aborted || options.timeoutMillis === 0n) {
      return Promise.reject(new Profile.ClientError({ category: options.signal?.aborted ? Profile.FailureCategory.LocalCancelled : Profile.FailureCategory.Deadline,
        message: "not-dispatched", dispatched: false, outcome: Profile.OutcomeKnowledge.NotDispatched, identity }));
    }
    check(request.expectedGeneration !== undefined && request.operationId !== "" && request.policy, "preconditioned fixture mutation");
    this.applyCalls++;
    if (this.receipt) return this.response({ receipt: structuredClone(this.receipt) }, identity);
    this.policy = structuredClone(request.policy);
    this.receipt = { operationId: request.operationId, tenant: "tenant-a", id: request.policy.id,
      recordKind: request.policy.recordKind, generation: 18446744073709551615n, contentDigest: "digest-a", revoked: false };
    this.serverWrites++;
    this.waiters++;
    return new Promise((_resolve, reject) => {
      const aborted = (): void => {
        this.waiters--;
        options.signal?.removeEventListener("abort", aborted);
        reject(new Profile.ClientError({ category: Profile.FailureCategory.LocalCancelled, message: "local-cancelled",
          dispatched: true, outcome: Profile.OutcomeKnowledge.Unknown, identity }));
      };
      options.signal?.addEventListener("abort", aborted, { once: true });
    });
  }

  getPolicyOperation(request: Profile.GetPolicyOperationRequest): Promise<Profile.ClientResponse<Profile.GetPolicyOperationResponse>> {
    const receipt = this.receipt?.operationId === request.operationId ? structuredClone(this.receipt) : undefined;
    return Promise.resolve({ value: receipt ? { receipt } : {}, metadata: metadata({ operationId: request.operationId },
      receipt ? Profile.OutcomeKnowledge.Observed : Profile.OutcomeKnowledge.Unknown) });
  }
}

const client = new FixtureClient();
const profile: Profile.ClientProfile = client;
const policy: Profile.Policy = { id: "policy-a", document: "{}", generation: 0n,
  language: "lsf-capability-policy-v1", recordKind: Profile.CapabilityPolicyRecordKind.Policy, contentDigest: "", revoked: false };
const request: Profile.ApplyPolicyRequest = { policy, expectedGeneration: 0n, operationId: "operation-a" };
const controller = new AbortController();
const pending = profile.applyPolicy(request, { signal: controller.signal });
check(client.serverWrites === 1 && client.waiters === 1, "remote receipt exists before local completion");
controller.abort();
try {
  await pending;
  throw new Error("local cancellation must fail the wait");
} catch (failure) {
  check(failure instanceof Profile.ClientError, "typed local failure");
  check(failure.failure.identity.operationId === "operation-a" && failure.failure.dispatched, "recovery identity survives local cancellation");
  check(failure.failure.outcome === Profile.OutcomeKnowledge.Unknown, "local cancellation is not remote rollback");
}
check(Number(client.waiters) === 0 && client.serverWrites === 1 && client.cancelCalls === 0, "only local ownership ends");
const recovered = await profile.getPolicyOperation({ operationId: "operation-a" });
check(recovered.value.receipt?.generation === 18446744073709551615n && recovered.metadata.auditAck === undefined, "retained original receipt without invented audit");
const unknown = await profile.getPolicyOperation({ operationId: "not-retained" });
check(unknown.value.receipt === undefined && unknown.metadata.outcome === Profile.OutcomeKnowledge.Unknown, "missing recovery remains unknown");
await profile.applyPolicy(request);
check(client.applyCalls === 2 && client.serverWrites === 1, "only explicit replay and no second remote write");
try {
  await profile.applyPolicy(request, { timeoutMillis: 0n });
  throw new Error("zero timeout must fail before dispatch");
} catch (failure) {
  check(failure instanceof Profile.ClientError && !failure.failure.dispatched, "zero timeout remains local");
}
const payload = new Uint8Array([1, 2, 3]);
const invoked = await profile.invoke({ activationId: "activation-a", payload, mediaType: "application/octet-stream", priority: 0, metadata: {} });
payload[0] = 99;
check(invoked.value.success?.payload[0] === 1, "returned response does not alias request storage");
check((await profile.cancel({ activationId: "activation-a", reason: "fixture" })).value.disposition === Profile.CancelDisposition.Accepted, "explicit remote cancellation");
check((await profile.getActivation({ activationId: "activation-a" })).value.phase === "running", "accepted is not terminal cleanup");
check((await profile.getPolicy({ id: "policy-a", recordKind: Profile.CapabilityPolicyRecordKind.Policy })).value.policy?.id === "policy-a", "policy inspection");
check((await profile.listPolicies({ recordKind: Profile.CapabilityPolicyRecordKind.Policy, page: { pageSize: 1 } })).value.page?.nextPageToken === "opaque-next-page", "bounded one-page response");
check(client.pageCalls === 1, "no automatic page draining");
check((await profile.listCapabilities({ deploymentId: "deployment-a", includeNodeUsage: false })).value.revision?.deploymentId === "deployment-a", "explicit selected deployment");
console.log("shared profile lifetime/recovery: passed");
