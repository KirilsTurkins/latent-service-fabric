import { inspect } from "node:util";
import * as profile from "../management.js";
import { decode } from "./protocol/codec.js";
import { registry } from "./protocol/schema.js";

export type Failure = profile.ClientFailure & {
  readonly unsupportedWireValue?: { readonly field: string; readonly value: string };
};

export class RpcError extends profile.ClientError {
  declare readonly failure: Failure;
  constructor(value: Failure) {
    super(value);
    Object.defineProperty(this, "failure", { value, enumerable: false });
  }
  [inspect.custom](): string { return `RpcError(category=${this.failure.category}, outcome=${this.failure.outcome})`; }
}

export function failure(category: number, identity: profile.RequestIdentity, dispatched: boolean, extra: Partial<Failure> = {}): RpcError {
  return new RpcError({
    category, message: "bounded RPC request failed", identity, dispatched,
    outcome: dispatched ? profile.OutcomeKnowledge.Unknown : profile.OutcomeKnowledge.NotDispatched,
    ...extra,
  });
}

export function identity(value: unknown): profile.RequestIdentity {
  if (!value || typeof value !== "object") return {};
  const object = value as Record<string, unknown>;
  const activationId = object.activationId;
  const operationId = object.operationId;
  return {
    ...(typeof activationId === "string" && activationId.length <= 256 ? { activationId } : {}),
    ...(typeof operationId === "string" && operationId.length <= 256 ? { operationId } : {}),
  };
}

export type Audit = Pick<profile.ResponseMetadata, "auditAck" | "auditStatus">;

export function audit(headers: ReadonlyMap<string, string>): Audit {
  const status = headers.get("latent-audit-status");
  const attempt = headers.get("latent-audit-attempt");
  if (status === undefined) {
    if (attempt !== undefined) throw new Error("audit sequence without status");
    return {};
  }
  if (!/^[a-z][a-z-]{0,63}$/.test(status)) throw new Error("invalid audit status");
  const codes: Record<string, number> = { durable: 1, "outcome-unknown": 2, "audit-unavailable": 3, disabled: 4 };
  const sequence = attempt === undefined ? undefined : profile.parseU64Decimal(attempt);
  if (sequence === 0n || ((status === "durable" || status === "outcome-unknown") && sequence === undefined)) throw new Error("invalid audit sequence");
  const code = codes[status];
  return {
    auditStatus: status,
    ...(code === undefined ? {} : { auditAck: { status: code, ...(sequence === undefined ? {} : { attemptSequence: sequence }) } }),
  };
}

const grpcCodes: Record<string, number> = {
  unavailable: 14, "route-unavailable": 14, "deadline-exceeded": 4, cancelled: 1,
  "resource-exhausted": 8, "admission-rejected": 8, "permission-denied": 7, unauthenticated: 16,
  "invalid-argument": 3, "not-found": 5, "already-exists": 6, "incompatible-contract": 9,
  "dependency-failed": 9, "state-conflict": 10, "corrupt-artifact": 15,
  internal: 13, "guest-trap": 13,
};

export function rpcFailure(code: number, headers: ReadonlyMap<string, string>, request: profile.RequestIdentity): RpcError {
  const acknowledgement = audit(headers);
  const extra: Partial<Failure> = { grpcStatus: code, ...acknowledgement };
  const details = headers.get("grpc-status-details-bin");
  if (details !== undefined) {
    if (details.length > 10924 || !/^[A-Za-z0-9+/]*={0,2}$/.test(details)) throw new Error("invalid platform details");
    const bytes = Buffer.from(details, "base64");
    if (bytes.toString("base64").replace(/=+$/, "") !== details.replace(/=+$/, "")) throw new Error("noncanonical platform details");
    const schema = registry.getMessage("latent.control.v1.PlatformError")!;
    const platform = decode(schema, bytes, 8192) as unknown as profile.PlatformError;
    if (platform.code.length > 64) throw new Error("platform code bound");
    const expected = grpcCodes[platform.code];
    if (expected === undefined) return failure(profile.FailureCategory.Decode, request, true, {
      ...extra, unsupportedWireValue: { field: "platform_error.code", value: platform.code },
    });
    if (expected !== code || platform.code.length > 64 || platform.message.length > 4096 || platform.detailItems.length > 16) throw new Error("inconsistent platform details");
    Object.assign(extra, { platformError: platform });
  }
  const observed = [3, 5, 6, 7, 9, 10, 12, 16].includes(code)
    && acknowledgement.auditStatus !== "outcome-unknown" && acknowledgement.auditStatus !== "audit-unavailable";
  return failure(code === 4 ? profile.FailureCategory.Deadline : profile.FailureCategory.Rpc, request, true,
    { ...extra, outcome: observed ? profile.OutcomeKnowledge.Observed : profile.OutcomeKnowledge.Unknown });
}
