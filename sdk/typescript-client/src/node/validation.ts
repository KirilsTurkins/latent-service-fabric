import * as profile from "../management.js";
import { type Operation } from "./protocol/schema.js";
import { ShapeError } from "./protocol/preflight.js";

type RecordValue = Record<string, unknown>;

function object(value: unknown): RecordValue {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new ShapeError();
  return value as RecordValue;
}

function bounded(value: unknown, maximum = 256): void {
  if (value !== undefined && (typeof value !== "string" || value.length > maximum)) throw new ShapeError();
}

export function validateRequest(operation: Operation, value: unknown, tenant: string): void {
  const request = object(value);
  for (const key of ["activationId", "rootActivationId", "parentActivationId", "operationId", "id", "deploymentId"]) bounded(request[key]);
  if (operation === "invoke") {
    const target = object(request.target);
    if (target.tenant !== tenant) throw new ShapeError();
    for (const key of ["service", "contract", "function", "route"]) bounded(target[key]);
    bounded(request.idempotencyKey);
    bounded(request.mediaType, 128);
  }
  if (operation === "listPolicies" || operation === "listCapabilities") {
    const page = object(request.page);
    if (typeof page.pageSize !== "number" || !Number.isInteger(page.pageSize) || page.pageSize < 1 || page.pageSize > 64) throw new ShapeError();
    bounded(page.pageToken, 2048);
  }
  if (operation === "applyPolicy") {
    const policy = object(request.policy);
    if (request.operationId === "" || request.operationId === undefined || request.expectedGeneration === undefined) throw new ShapeError();
    bounded(policy.id);
    if (policy.metadata !== undefined) {
      const metadata = object(policy.metadata);
      if (metadata.tenant !== undefined && metadata.tenant !== tenant) throw new ShapeError();
    }
  }
}

export function validateResponse(operation: Operation, request: unknown, raw: RecordValue, tenant: string): void {
  const input = object(request);
  if (operation === "invoke" || operation === "getActivation") {
    if (typeof raw.activationId !== "string" || !raw.activationId || raw.activationId.length > 256
      || /\s/.test(raw.activationId) || (input.activationId !== undefined && raw.activationId !== input.activationId)) throw new ShapeError();
  }
  if (operation === "invoke") {
    if ([raw.success, raw.declaredError, raw.platformFailure].filter((value) => value !== undefined).length !== 1 || raw.consumption === undefined) throw new ShapeError();
    bounded(raw.revisionId);
    bounded(raw.releaseDigest);
    if (raw.publicationId !== undefined && (typeof raw.publicationId !== "string" || !/^publication:sha256:[0-9a-f]{64}$/.test(raw.publicationId))) throw new ShapeError();
    const unresolved = raw.revisionId === "" && raw.releaseDigest === "" && raw.routeGeneration === 0n && raw.publicationId === undefined && raw.platformFailure !== undefined;
    if (!unresolved && (!raw.revisionId || !raw.releaseDigest)) throw new ShapeError();
  }
  if (operation === "cancel") {
    if (raw.disposition !== 1 && raw.disposition !== 2 && raw.disposition !== 3) throw new ShapeError("cancel.disposition", String(raw.disposition));
    if (!((raw.disposition === 1 || raw.disposition === 3) && raw.terminalState === undefined)
      && !(raw.disposition === 2 && typeof raw.terminalState === "string" && raw.terminalState.length > 0)) throw new ShapeError();
  }
  if (operation === "getActivation") {
    const hasTerminal = raw.terminalState !== undefined;
    if (hasTerminal !== (raw.finalConsumption !== undefined) || hasTerminal !== (raw.terminalAtUnixMillis !== undefined)
      || [raw.succeeded, raw.declaredError, raw.platformFailure].filter((value) => value !== undefined).length !== (hasTerminal ? 1 : 0)) throw new ShapeError();
    if ((raw.succeeded !== undefined || raw.declaredError !== undefined) && raw.terminalState !== "completed") throw new ShapeError();
  }
  if (operation === "listPolicies" || operation === "listCapabilities") {
    const page = object(raw.page);
    bounded(page.nextPageToken, 2048);
    const items = operation === "listPolicies" ? raw.policies : raw.capabilities;
    if (!Array.isArray(items) || items.length > (object(input.page).pageSize as number) || page.nextPageToken === "") throw new ShapeError();
  }
  if (operation === "applyPolicy") {
    const policy = object(raw.policy);
    const receipt = object(raw.receipt);
    if (receipt.operationId !== input.operationId || receipt.tenant !== tenant || receipt.id !== object(input.policy).id
      || ["id", "recordKind", "generation", "contentDigest", "revoked"].some((key) => receipt[key] !== policy[key])) throw new ShapeError();
  }
  if (operation === "getPolicyOperation" && raw.receipt !== undefined) {
    const receipt = object(raw.receipt);
    if (receipt.operationId !== input.operationId || receipt.tenant !== tenant) throw new ShapeError();
  }
}

export function outcome(operation: Operation, response: RecordValue): number {
  return operation === "getPolicyOperation" && response.receipt === undefined ? profile.OutcomeKnowledge.Unknown : profile.OutcomeKnowledge.Observed;
}
