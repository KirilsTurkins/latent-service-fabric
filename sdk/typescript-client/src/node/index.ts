import { sensitiveHeaders } from "node:http2";
import { performance } from "node:perf_hooks";
import * as profile from "../management.js";
import type * as transaction from "../transactions.js";
import type * as transactionClient from "../transaction-client.js";
import * as transactions from "./transaction.js";
import { Channel } from "./channel.js";
import { configuration, type ClientConfig, type ClientLimits } from "./config.js";
import { failure, identity, RpcError } from "./errors.js";
import { exchange } from "./exchange.js";
import { encode, decode } from "./protocol/codec.js";
import { method, isTransaction, type Operation } from "./protocol/schema.js";
import { validateRequest } from "./validation.js";

export type { ClientConfig, ClientLimits } from "./config.js";
export { RpcError } from "./errors.js";

export interface ClientUsage {
  readonly activeCalls: number;
  readonly reservedMessageBytes: number;
  readonly sessions: number;
  readonly sockets: number;
  readonly closed: boolean;
}

export class RpcClient implements profile.ClientProfile, transactionClient.TransactionClient {
  readonly #channel: Channel;
  readonly #credential: Buffer;
  readonly #tenant: string;
  readonly #limits: ClientLimits;
  #calls = 0;
  #bytes = 0;
  #waiter: (() => void) | undefined;
  #shutdown: Promise<void> | undefined;

  constructor(config: ClientConfig) {
    const selected = configuration(config);
    this.#limits = selected.limits;
    this.#tenant = config.tenant;
    this.#credential = Buffer.from(config.credential);
    this.#channel = new Channel(config.endpoint, selected.host, selected.port, selected.limits, () => this.#waiter?.());
  }

  get limits(): ClientLimits { return this.#limits; }
  usage(): ClientUsage {
    return { activeCalls: this.#calls, reservedMessageBytes: this.#bytes, sessions: this.#channel.sessions, sockets: this.#channel.sockets, closed: this.#channel.closed };
  }

  invoke(request: profile.InvokeRequest, options?: profile.CallOptions): Promise<profile.ClientResponse<profile.InvokeResponse>> { return this.call("invoke", request, options); }
  cancel(request: profile.CancelRequest, options?: profile.CallOptions): Promise<profile.ClientResponse<profile.CancelResponse>> { return this.call("cancel", request, options); }
  getActivation(request: profile.GetActivationRequest, options?: profile.CallOptions): Promise<profile.ClientResponse<profile.ActivationStatus>> { return this.call("getActivation", request, options); }
  getPolicy(request: profile.GetPolicyRequest, options?: profile.CallOptions): Promise<profile.ClientResponse<profile.GetPolicyResponse>> { return this.call("getPolicy", request, options); }
  listPolicies(request: profile.ListPoliciesRequest, options?: profile.CallOptions): Promise<profile.ClientResponse<profile.ListPoliciesResponse>> { return this.call("listPolicies", request, options); }
  listCapabilities(request: profile.ListCapabilitiesRequest, options?: profile.CallOptions): Promise<profile.ClientResponse<profile.ListCapabilitiesResponse>> { return this.call("listCapabilities", request, options); }
  applyPolicy(request: profile.ApplyPolicyRequest, options?: profile.CallOptions): Promise<profile.ClientResponse<profile.ApplyPolicyResponse>> { return this.call("applyPolicy", request, options); }
  getPolicyOperation(request: profile.GetPolicyOperationRequest, options?: profile.CallOptions): Promise<profile.ClientResponse<profile.GetPolicyOperationResponse>> { return this.call("getPolicyOperation", request, options); }

  invokeCommand(request: transaction.InvokeCommandRequest, options?: profile.CallOptions): Promise<transactionClient.ClientResponse<transaction.InvokeCommandResponse>> { return this.transactionCall("invokeCommand", request, options); }
  query(request: transaction.QueryRequest, options?: profile.CallOptions): Promise<transactionClient.ClientResponse<transaction.QueryResponse>> { return this.transactionCall("query", request, options); }
  lookupCommand(request: transaction.LookupCommandRequest, options?: profile.CallOptions): Promise<transactionClient.ClientResponse<transaction.LookupCommandResponse>> { return this.transactionCall("lookupCommand", request, options); }
  lookupCommit(request: transaction.LookupCommitRequest, options?: profile.CallOptions): Promise<transactionClient.ClientResponse<transaction.LookupCommitResponse>> { return this.transactionCall("lookupCommit", request, options); }
  getEffect(request: transaction.GetEffectRequest, options?: profile.CallOptions): Promise<transactionClient.ClientResponse<transaction.GetEffectResponse>> { return this.transactionCall("getEffect", request, options); }
  listEffectHistory(request: transaction.ListEffectHistoryRequest, options?: profile.CallOptions): Promise<transactionClient.ClientResponse<transaction.ListEffectHistoryResponse>> { return this.transactionCall("listEffectHistory", request, options); }
  cancelCommand(request: transaction.CancelCommandRequest, options?: profile.CallOptions): Promise<transactionClient.ClientResponse<transaction.CancelCommandResponse>> { return this.transactionCall("cancelCommand", request, options); }
  inspectNamespace(request: transaction.InspectNamespaceRequest, options?: profile.CallOptions): Promise<transactionClient.ClientResponse<transaction.InspectNamespaceResponse>> { return this.transactionCall("inspectNamespace", request, options); }
  mutateNamespace(request: transaction.MutateNamespaceRequest, options?: profile.CallOptions): Promise<transactionClient.ClientResponse<transaction.MutateNamespaceResponse>> { return this.transactionCall("mutateNamespace", request, options); }
  selectEntity(request: transaction.SelectEntityRequest, options?: profile.CallOptions): Promise<transactionClient.ClientResponse<transaction.SelectEntityResponse>> { return this.transactionCall("selectEntity", request, options); }
  mutateState(request: transaction.MutateStateRequest, options?: profile.CallOptions): Promise<transactionClient.ClientResponse<transaction.MutateStateResponse>> { return this.transactionCall("mutateState", request, options); }
  getStateOperationReceipt(request: transaction.GetStateOperationReceiptRequest, options?: profile.CallOptions): Promise<transactionClient.ClientResponse<transaction.GetStateOperationReceiptResponse>> { return this.transactionCall("getStateOperationReceipt", request, options); }
  inspectDispatcher(request: transaction.InspectDispatcherRequest, options?: profile.CallOptions): Promise<transactionClient.ClientResponse<transaction.InspectDispatcherResponse>> { return this.transactionCall("inspectDispatcher", request, options); }
  controlDispatcher(request: transaction.ControlDispatcherRequest, options?: profile.CallOptions): Promise<transactionClient.ClientResponse<transaction.ControlDispatcherResponse>> { return this.transactionCall("controlDispatcher", request, options); }
  getDispatcherOperation(request: transaction.GetDispatcherOperationRequest, options?: profile.CallOptions): Promise<transactionClient.ClientResponse<transaction.GetDispatcherOperationResponse>> { return this.transactionCall("getDispatcherOperation", request, options); }

  private transactionCall<Response>(operation: Operation, request: unknown, options?: profile.CallOptions): Promise<transactionClient.ClientResponse<Response>> {
    return this.call<Response>(operation, request, options).then((response) => response as transactionClient.ClientResponse<Response>)
      .catch((error: unknown) => {
        if (error instanceof RpcError && error.failure.transactionIdentity === undefined)
          throw new RpcError({ ...error.failure, transactionIdentity: transactions.identity(operation, request) });
        throw error;
      });
  }

  shutdown(timeoutMillis = 5000): Promise<void> {
    if (!Number.isSafeInteger(timeoutMillis) || timeoutMillis < 0 || timeoutMillis > 300000) return Promise.reject(failure(profile.FailureCategory.InvalidRequest, {}, false));
    if (this.#shutdown) return this.#shutdown;
    this.#channel.close();
    this.#credential.fill(0);
    const pending = new Promise<void>((resolve, reject) => {
      const timer = setTimeout(() => {
        this.#waiter = undefined;
        reject(failure(profile.FailureCategory.Deadline, {}, false));
      }, timeoutMillis);
      this.#waiter = () => {
        const current = this.usage();
        if (current.activeCalls === 0 && current.sessions === 0 && current.sockets === 0) {
          clearTimeout(timer);
          this.#waiter = undefined;
          resolve();
        }
      };
      this.#waiter();
    });
    this.#shutdown = pending.finally(() => { this.#shutdown = undefined; });
    return this.#shutdown;
  }

  private call<Response>(operation: Operation, request: unknown, options: profile.CallOptions = {}): Promise<profile.ClientResponse<Response>> {
    const transactional = isTransaction(operation);
    let recovery = transactional ? transactions.identity(operation, request) : identity(request);
    const local = (category: number) => failure(category, recovery, false, transactional ? { transactionIdentity: recovery } : {});
    if (!request || typeof request !== "object" || !options || typeof options !== "object"
      || (options.signal !== undefined && !(options.signal instanceof AbortSignal))) return Promise.reject(local(profile.FailureCategory.InvalidRequest));
    if (this.#channel.closed || options.signal?.aborted) return Promise.reject(local(profile.FailureCategory.LocalCancelled));
    const relative = options.timeoutMillis ?? BigInt(this.#limits.rpcTimeoutMillis);
    if (typeof relative !== "bigint" || relative < 0n || relative > 300000n) return Promise.reject(local(profile.FailureCategory.InvalidRequest));
    let deadline = performance.now() + Math.min(Number(relative), this.#limits.rpcTimeoutMillis);
    if (operation === "invoke" || operation === "invokeCommand" || operation === "query") {
      const wall = operation === "invoke" ? (request as profile.InvokeRequest).deadlineUnixMillis
        : (request as transaction.InvokeCommandRequest).invocation?.deadlineUnixMillis;
      if (wall !== undefined) {
        if (typeof wall !== "bigint" || wall < 0n || wall > 18446744073709551615n) return Promise.reject(local(profile.FailureCategory.InvalidRequest));
        const remaining = wall - BigInt(Date.now());
        deadline = Math.min(deadline, performance.now() + Number(remaining <= 0n ? 0n : remaining > 300000n ? 300000n : remaining));
      }
    }
    if (performance.now() >= deadline) return Promise.reject(local(profile.FailureCategory.Deadline));
    const maximumRequest = Math.min(this.#limits.maximumRequestBytes, transactional ? 2 * 1024 * 1024 : this.#limits.maximumRequestBytes);
    const maximumResponse = Math.min(this.#limits.maximumResponseBytes, transactional ? 2 * 1024 * 1024 : this.#limits.maximumResponseBytes);
    const reserved = 2 * (maximumRequest + maximumResponse) + 65536 + (transactional ? 8 * 1024 * 1024 + 384 * 1024 : 0);
    if (this.#calls >= this.#limits.maximumCalls || reserved > this.#limits.maximumReservedBytes - this.#bytes) return Promise.reject(local(profile.FailureCategory.Limit));
    this.#calls++;
    this.#bytes += reserved;
    let retired = false;
    const retire = () => {
      if (retired) return;
      retired = true;
      this.#calls--;
      this.#bytes -= reserved;
      this.#waiter?.();
    };
    let encoded: Uint8Array;
    let context: unknown;
    try {
      if (transactional) transactions.validateRequest(operation, request, this.#tenant); else validateRequest(operation, request, this.#tenant);
      encoded = encode(method(operation).input, request, maximumRequest, transactional);
      if (transactional) {
        const snapshot = decode(method(operation).input, encoded, maximumRequest, true);
        recovery = transactions.identity(operation, snapshot);
        context = transactions.context(operation, snapshot);
      } else {
      const value = request as Record<string, unknown>;
      context = {
        ...recovery,
        ...(value.page === undefined ? {} : { page: { pageSize: (value.page as profile.PageRequest).pageSize } }),
        ...(value.policy === undefined ? {} : { policy: { id: (value.policy as profile.Policy).id } }),
      };
      }
    } catch {
      retire();
      return Promise.reject(local(profile.FailureCategory.InvalidRequest));
    }
    if (performance.now() >= deadline) {
      retire();
      return Promise.reject(local(profile.FailureCategory.Deadline));
    }
    try {
      const session = this.#channel.get(deadline);
      const descriptor = method(operation);
      const frame = Buffer.allocUnsafe(encoded.length + 5);
      frame[0] = 0;
      frame.writeUInt32BE(encoded.length, 1);
      frame.set(encoded, 5);
      const stream = session.request({
        ":method": "POST", ":path": `/${descriptor.parent.typeName}/${descriptor.name}`,
        "content-type": "application/grpc+proto", te: "trailers", "grpc-accept-encoding": "identity",
        "grpc-timeout": `${Math.max(1, Math.ceil(deadline - performance.now()))}m`,
        authorization: `Bearer ${this.#credential.toString("ascii")}`,
        [sensitiveHeaders]: ["authorization"],
      });
      return exchange(stream, frame, {
        operation, request: context, tenant: this.#tenant, identity: recovery, deadline,
        maximum: maximumResponse, signal: options.signal,
        ...(transactional ? { transactionIdentity: recovery } : {}),
        closed: () => this.#channel.closed, retired: retire,
      });
    } catch {
      retire();
      return Promise.reject(local(profile.FailureCategory.Transport));
    }
  }
}
