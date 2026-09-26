import { isIP } from "node:net";

export interface ClientLimits {
  readonly maximumCalls: number;
  readonly maximumRequestBytes: number;
  readonly maximumResponseBytes: number;
  readonly maximumReservedBytes: number;
  readonly connectTimeoutMillis: number;
  readonly rpcTimeoutMillis: number;
}

export interface ClientConfig {
  readonly endpoint: string;
  readonly tenant: string;
  readonly credential: Uint8Array;
  readonly limits?: Partial<ClientLimits>;
}

export const defaults: ClientLimits = Object.freeze({
  maximumCalls: 8,
  maximumRequestBytes: 262144,
  maximumResponseBytes: 262144,
  maximumReservedBytes: 16 * 1024 * 1024,
  connectTimeoutMillis: 3000,
  rpcTimeoutMillis: 10000,
});

export function configuration(value: ClientConfig): { host: string; port: number; limits: ClientLimits } {
  if (!value || typeof value.endpoint !== "string" || value.endpoint.length > 256
    || typeof value.tenant !== "string" || !/^[A-Za-z0-9](?:[A-Za-z0-9_.-]{0,126}[A-Za-z0-9])?$/.test(value.tenant)
    || !(value.credential instanceof Uint8Array) || value.credential.length < 32 || value.credential.length > 256
    || !value.credential.every((byte) => (byte >= 48 && byte <= 57) || (byte >= 65 && byte <= 90)
      || (byte >= 97 && byte <= 122) || byte === 45 || byte === 95)) throw new RangeError("invalid explicit client configuration");
  let url: URL;
  try { url = new URL(value.endpoint); } catch { throw new RangeError("invalid explicit client endpoint"); }
  const host = url.hostname.replace(/^\[|\]$/g, "");
  const port = Number(url.port || "80");
  if (url.protocol !== "http:" || url.username || url.password || url.search || url.hash || url.pathname !== "/"
    || !isIP(host) || !(host === "::1" || /^127\./.test(host))
    || !Number.isInteger(port) || port < 1 || port > 65535
    || value.endpoint !== `http://${isIP(host) === 6 ? `[${host}]` : host}:${port}`) throw new RangeError("numeric loopback endpoint required");
  const limits = Object.freeze({ ...defaults, ...value.limits });
  const caps: ClientLimits = {
    maximumCalls: 32, maximumRequestBytes: 4 * 1024 * 1024, maximumResponseBytes: 4 * 1024 * 1024,
    maximumReservedBytes: 64 * 1024 * 1024, connectTimeoutMillis: 300000, rpcTimeoutMillis: 300000,
  };
  for (const key of Object.keys(caps) as (keyof ClientLimits)[]) {
    if (!Number.isSafeInteger(limits[key]) || limits[key] <= 0 || limits[key] > caps[key]) throw new RangeError("invalid finite client limit");
  }
  return { host, port, limits };
}
