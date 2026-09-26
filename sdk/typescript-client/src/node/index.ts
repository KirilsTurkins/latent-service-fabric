import { sensitiveHeaders } from "node:http2";
import { performance } from "node:perf_hooks";
import * as profile from "../management.js";
import { Channel } from "./channel.js";
import { configuration, type ClientConfig, type ClientLimits } from "./config.js";
import { failure, identity } from "./errors.js";
import { exchange } from "./exchange.js";
import { encode } from "./protocol/codec.js";
import { method, type Operation } from "./protocol/schema.js";
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

export class RpcClient implements profile.ClientProfile {
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
    const recovery = identity(request);
    if (!request || typeof request !== "object" || !options || typeof options !== "object"
      || (options.signal !== undefined && !(options.signal instanceof AbortSignal))) return Promise.reject(failure(profile.FailureCategory.InvalidRequest, recovery, false));
    if (this.#channel.closed || options.signal?.aborted) return Promise.reject(failure(profile.FailureCategory.LocalCancelled, recovery, false));
    const relative = options.timeoutMillis ?? BigInt(this.#limits.rpcTimeoutMillis);
    if (typeof relative !== "bigint" || relative < 0n || relative > 300000n) return Promise.reject(failure(profile.FailureCategory.InvalidRequest, recovery, false));
    let deadline = performance.now() + Math.min(Number(relative), this.#limits.rpcTimeoutMillis);
    if (operation === "invoke") {
      const wall = (request as profile.InvokeRequest).deadlineUnixMillis;
      if (wall !== undefined) {
        if (typeof wall !== "bigint" || wall < 0n || wall > 18446744073709551615n) return Promise.reject(failure(profile.FailureCategory.InvalidRequest, recovery, false));
        const remaining = wall - BigInt(Date.now());
        deadline = Math.min(deadline, performance.now() + Number(remaining <= 0n ? 0n : remaining > 300000n ? 300000n : remaining));
      }
    }
    if (performance.now() >= deadline) return Promise.reject(failure(profile.FailureCategory.Deadline, recovery, false));
    const reserved = 2 * (this.#limits.maximumRequestBytes + this.#limits.maximumResponseBytes) + 65536;
    if (this.#calls >= this.#limits.maximumCalls || reserved > this.#limits.maximumReservedBytes - this.#bytes) return Promise.reject(failure(profile.FailureCategory.Limit, recovery, false));
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
      validateRequest(operation, request, this.#tenant);
      encoded = encode(method(operation).input, request, this.#limits.maximumRequestBytes);
      const value = request as Record<string, unknown>;
      context = {
        ...recovery,
        ...(value.page === undefined ? {} : { page: { pageSize: (value.page as profile.PageRequest).pageSize } }),
        ...(value.policy === undefined ? {} : { policy: { id: (value.policy as profile.Policy).id } }),
      };
    } catch {
      retire();
      return Promise.reject(failure(profile.FailureCategory.InvalidRequest, recovery, false));
    }
    if (performance.now() >= deadline) {
      retire();
      return Promise.reject(failure(profile.FailureCategory.Deadline, recovery, false));
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
        maximum: this.#limits.maximumResponseBytes, signal: options.signal,
        closed: () => this.#channel.closed, retired: retire,
      });
    } catch {
      retire();
      return Promise.reject(failure(profile.FailureCategory.Transport, recovery, false));
    }
  }
}
