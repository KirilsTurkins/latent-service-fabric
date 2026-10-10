import { constants, type ClientHttp2Stream, type IncomingHttpHeaders, type IncomingHttpStatusHeader } from "node:http2";
import { performance } from "node:perf_hooks";
import * as profile from "../management.js";
import type { RecoveryIdentity, ObservedOutcome } from "../transaction-client.js";
import { audit, failure, rpcFailure, RpcError, type Audit, type Failure } from "./errors.js";
import { decode } from "./protocol/codec.js";
import { method, isTransaction, type Operation } from "./protocol/schema.js";
import { ShapeError } from "./protocol/preflight.js";
import { outcome, validateResponse } from "./validation.js";
import * as transactions from "./transaction.js";

export interface ExchangeOptions {
  readonly operation: Operation;
  readonly request: unknown;
  readonly tenant: string;
  readonly identity: profile.RequestIdentity;
  readonly deadline: number;
  readonly maximum: number;
  readonly signal: AbortSignal | undefined;
  readonly closed: () => boolean;
  readonly retired: () => void;
  readonly transactionIdentity?: RecoveryIdentity;
}

export function exchange<Response>(stream: ClientHttp2Stream, frame: Buffer, options: ExchangeOptions): Promise<profile.ClientResponse<Response>> {
  return new Promise((resolve, reject) => {
    const transactional = isTransaction(options.operation);
    let transactionIdentity = options.transactionIdentity ?? {};
    let observed: ObservedOutcome | undefined;
    const problem = (category: number, extra: Partial<Failure> = {}) => failure(category, options.identity, true, {
      ...extra,
      ...(transactional ? {
        transactionIdentity,
        ...(observed === undefined ? {} : { observedTransaction: observed }),
        outcome: transactions.known(observed) ? profile.OutcomeKnowledge.Observed : profile.OutcomeKnowledge.Unknown,
      } : {}),
    });
    let buffer: Buffer | undefined;
    try { buffer = Buffer.allocUnsafe(options.maximum + 5); } catch {
      stream.once("close", options.retired);
      stream.destroy();
      reject(problem(profile.FailureCategory.Limit));
      return;
    }
    let used = 0;
    let done = false;
    let pendingError: RpcError | undefined;
    let pendingResult: profile.ClientResponse<Response> | undefined;
    let responseSeen = false;
    let trailersSeen = false;
    let headerBytes = 0;
    let acknowledgement: Audit = {};
    let grpcStatus: number | undefined;
    const headers = new Map<string, string>();
    const timer = setTimeout(() => stop(problem(profile.FailureCategory.Deadline)), Math.max(1, Math.ceil(options.deadline - performance.now())));
    const aborted = () => stop(problem(profile.FailureCategory.LocalCancelled));

    function finish(error?: RpcError, result?: profile.ClientResponse<Response>): void {
      if (done) return;
      done = true;
      clearTimeout(timer);
      options.signal?.removeEventListener("abort", aborted);
      if (transactional) {
        // Keep the graph reservation with the original HTTP/2 body until its
        // close callback retires it. A completed await can then admit recovery.
        pendingError = error;
        pendingResult = result;
      } else if (error) reject(error); else resolve(result!);
    }

    function stop(error: RpcError): void {
      finish(error);
      if (!stream.closed && !stream.destroyed) stream.close(constants.NGHTTP2_CANCEL);
      stream.destroy();
    }

    function headerBlock(block: IncomingHttpHeaders & IncomingHttpStatusHeader, raw: string[], trailers: boolean): void {
      if (done) return;
      try {
        if ((trailers && trailersSeen) || (!trailers && responseSeen)) throw new Error("duplicate header block");
        if (trailers) trailersSeen = true; else responseSeen = true;
        const seen = new Set<string>();
        for (let index = 0; index < raw.length; index += 2) {
          const name = raw[index]!;
          const value = raw[index + 1]!;
          if (seen.has(name)) throw new Error("duplicate header");
          seen.add(name);
          headerBytes += Buffer.byteLength(name) + Buffer.byteLength(value);
        }
        if (headerBytes > 16384 || seen.size > 32) throw new Error("header bounds");
        if (!trailers && (block[":status"] !== 200 || block["content-type"] !== "application/grpc" && block["content-type"] !== "application/grpc+proto")) throw new Error("invalid grpc response");
        for (const [name, value] of Object.entries(block)) {
          if (name.startsWith(":")) continue;
          if (typeof value !== "string" || headers.has(name)) throw new Error("ambiguous header");
          headers.set(name, value);
        }
        if (headers.size > 32) throw new Error("aggregate header count");
        if (headers.has("grpc-encoding") && headers.get("grpc-encoding") !== "identity") throw new Error("unsupported response encoding");
      } catch {
        stop(problem(profile.FailureCategory.Decode));
      }
    }

    stream.on("response", (block, _flags, raw) => headerBlock(block, raw, false));
    stream.on("trailers", (block, _flags, raw) => headerBlock(block, raw, true));
    stream.on("headers", () => stop(problem(profile.FailureCategory.Decode)));
    stream.on("data", (chunk: Buffer) => {
      if (done) return;
      if (!buffer || chunk.length > buffer.length - used) {
        stop(problem(profile.FailureCategory.Limit));
        return;
      }
      chunk.copy(buffer, used);
      used += chunk.length;
      if (used >= 5 && buffer[0] !== 0) stop(problem(profile.FailureCategory.Decode));
      else if (used >= 5 && buffer.readUInt32BE(1) > options.maximum) stop(problem(profile.FailureCategory.Limit));
    });
    stream.on("end", () => {
      if (done) return;
      if (options.closed()) {
        stop(problem(profile.FailureCategory.LocalCancelled));
        return;
      }
      try {
        if (performance.now() >= options.deadline) {
          stop(problem(profile.FailureCategory.Deadline));
          return;
        }
        const status = headers.get("grpc-status");
        if (!responseSeen || status === undefined || !/^(0|[1-9][0-9]{0,9})$/.test(status)) throw new Error("missing grpc status");
        const code = Number(status);
        if (code > 2147483647) throw new Error("invalid grpc status");
        grpcStatus = code;
        if (code !== 0) {
          acknowledgement = audit(headers);
          const error = rpcFailure(code, headers, options.identity,
            options.operation === "getActivation" || options.operation === "getPolicyOperation" || transactional);
          finish(transactional ? new RpcError({ ...error.failure, transactionIdentity, outcome: profile.OutcomeKnowledge.Unknown }) : error);
          return;
        }
        if (!transactional) acknowledgement = audit(headers);
        if (!buffer || used < 5 || buffer.readUInt32BE(1) !== used - 5) throw new Error("invalid unary frame");
        if (transactional && ["selectEntity", "listEffectHistory"].includes(options.operation) && used - 5 > 1048576) throw new ShapeError();
        const value = decode(method(options.operation).output, buffer.subarray(5, used), options.maximum, transactional);
        if (transactional) {
          transactions.validateResponse(options.operation, options.request, value, options.tenant);
          observed = transactions.observe(options.operation, value);
          transactionIdentity = transactions.extendIdentity(transactionIdentity, observed);
          transactions.validateIndependentAudit(value);
        } else validateResponse(options.operation, options.request, value, options.tenant);
        if (transactional) acknowledgement = audit(headers);
        const responseIdentity = options.operation === "invoke" && typeof value.activationId === "string" ? { activationId: value.activationId } : options.identity;
        finish(undefined, { value: value as unknown as Response, metadata: {
          identity: responseIdentity, outcome: transactional ? transactions.known(observed) ? profile.OutcomeKnowledge.Observed : profile.OutcomeKnowledge.Unknown : outcome(options.operation, value), ...acknowledgement,
          ...(transactional ? { transactionIdentity, ...(observed === undefined ? {} : { observedTransaction: observed }) } : {}),
        } });
      } catch (error) {
        stop(problem(profile.FailureCategory.Decode, {
          ...acknowledgement,
          ...(grpcStatus === undefined ? {} : { grpcStatus }),
          ...(error instanceof ShapeError && error.unsupportedWireValue ? { unsupportedWireValue: error.unsupportedWireValue } : {}),
        }));
      }
    });
    stream.on("error", () => {
      finish(problem(options.closed() ? profile.FailureCategory.LocalCancelled : profile.FailureCategory.Transport));
      stream.destroy();
    });
    stream.once("close", () => {
      finish(problem(options.closed() ? profile.FailureCategory.LocalCancelled : profile.FailureCategory.Transport));
      buffer = undefined;
      headers.clear();
      options.retired();
      if (transactional) {
        if (pendingError) reject(pendingError); else resolve(pendingResult!);
        pendingError = undefined;
        pendingResult = undefined;
      }
    });
    options.signal?.addEventListener("abort", aborted, { once: true });
    if (options.signal?.aborted) aborted();
    else {
      try { stream.end(frame); } catch { stop(problem(profile.FailureCategory.Transport)); }
    }
  });
}
