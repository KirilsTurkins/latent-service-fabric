import { constants, type ClientHttp2Stream, type IncomingHttpHeaders, type IncomingHttpStatusHeader } from "node:http2";
import { performance } from "node:perf_hooks";
import * as profile from "../management.js";
import { audit, failure, rpcFailure, type Audit, type RpcError } from "./errors.js";
import { decode } from "./protocol/codec.js";
import { method, type Operation } from "./protocol/schema.js";
import { ShapeError } from "./protocol/preflight.js";
import { outcome, validateResponse } from "./validation.js";

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
}

export function exchange<Response>(stream: ClientHttp2Stream, frame: Buffer, options: ExchangeOptions): Promise<profile.ClientResponse<Response>> {
  return new Promise((resolve, reject) => {
    let buffer: Buffer | undefined;
    try { buffer = Buffer.allocUnsafe(options.maximum + 5); } catch {
      stream.once("close", options.retired);
      stream.destroy();
      reject(failure(profile.FailureCategory.Limit, options.identity, true));
      return;
    }
    let used = 0;
    let done = false;
    let responseSeen = false;
    let trailersSeen = false;
    let headerBytes = 0;
    let acknowledgement: Audit = {};
    let grpcStatus: number | undefined;
    const headers = new Map<string, string>();
    const timer = setTimeout(() => stop(failure(profile.FailureCategory.Deadline, options.identity, true)), Math.max(1, Math.ceil(options.deadline - performance.now())));
    const aborted = () => stop(failure(profile.FailureCategory.LocalCancelled, options.identity, true));

    function finish(error?: RpcError, result?: profile.ClientResponse<Response>): void {
      if (done) return;
      done = true;
      clearTimeout(timer);
      options.signal?.removeEventListener("abort", aborted);
      if (error) reject(error); else resolve(result!);
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
        stop(failure(profile.FailureCategory.Decode, options.identity, true));
      }
    }

    stream.on("response", (block, _flags, raw) => headerBlock(block, raw, false));
    stream.on("trailers", (block, _flags, raw) => headerBlock(block, raw, true));
    stream.on("headers", () => stop(failure(profile.FailureCategory.Decode, options.identity, true)));
    stream.on("data", (chunk: Buffer) => {
      if (done) return;
      if (!buffer || chunk.length > buffer.length - used) {
        stop(failure(profile.FailureCategory.Limit, options.identity, true));
        return;
      }
      chunk.copy(buffer, used);
      used += chunk.length;
      if (used >= 5 && buffer[0] !== 0) stop(failure(profile.FailureCategory.Decode, options.identity, true));
      else if (used >= 5 && buffer.readUInt32BE(1) > options.maximum) stop(failure(profile.FailureCategory.Limit, options.identity, true));
    });
    stream.on("end", () => {
      if (done) return;
      if (options.closed()) {
        stop(failure(profile.FailureCategory.LocalCancelled, options.identity, true));
        return;
      }
      try {
        if (performance.now() >= options.deadline) {
          stop(failure(profile.FailureCategory.Deadline, options.identity, true));
          return;
        }
        const status = headers.get("grpc-status");
        if (!responseSeen || status === undefined || !/^(0|[1-9][0-9]{0,9})$/.test(status)) throw new Error("missing grpc status");
        const code = Number(status);
        if (code > 2147483647) throw new Error("invalid grpc status");
        grpcStatus = code;
        acknowledgement = audit(headers);
        if (code !== 0) {
          finish(rpcFailure(code, headers, options.identity,
            options.operation === "getActivation" || options.operation === "getPolicyOperation"));
          return;
        }
        if (!buffer || used < 5 || buffer.readUInt32BE(1) !== used - 5) throw new Error("invalid unary frame");
        const value = decode(method(options.operation).output, buffer.subarray(5, used), options.maximum);
        validateResponse(options.operation, options.request, value, options.tenant);
        const responseIdentity = options.operation === "invoke" && typeof value.activationId === "string" ? { activationId: value.activationId } : options.identity;
        finish(undefined, { value: value as unknown as Response, metadata: { identity: responseIdentity, outcome: outcome(options.operation, value), ...acknowledgement } });
      } catch (error) {
        stop(failure(profile.FailureCategory.Decode, options.identity, true, {
          ...acknowledgement,
          ...(grpcStatus === undefined ? {} : { grpcStatus }),
          ...(error instanceof ShapeError && error.unsupportedWireValue ? { unsupportedWireValue: error.unsupportedWireValue } : {}),
        }));
      }
    });
    stream.on("error", () => {
      finish(failure(options.closed() ? profile.FailureCategory.LocalCancelled : profile.FailureCategory.Transport, options.identity, true));
      stream.destroy();
    });
    stream.once("close", () => {
      finish(failure(options.closed() ? profile.FailureCategory.LocalCancelled : profile.FailureCategory.Transport, options.identity, true));
      buffer = undefined;
      headers.clear();
      options.retired();
    });
    options.signal?.addEventListener("abort", aborted, { once: true });
    if (options.signal?.aborted) aborted();
    else {
      try { stream.end(frame); } catch { stop(failure(profile.FailureCategory.Transport, options.identity, true)); }
    }
  });
}
