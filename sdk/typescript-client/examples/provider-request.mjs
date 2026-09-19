export const mediaType = "application/vnd.latent.wit-values.v1+json";

export function providerRequest(target, tenant, activationId, provider, text = "", functionName = target.function) {
  const callee = provider === "callee";
  return {
    activationId,
    target: { tenant, service: target.service, route: target.route, contract: target.contract, function: functionName },
    payload: Buffer.from(JSON.stringify(callee ? [] : [0, text, "0"])),
    mediaType, priority: 0, metadata: {},
    budget: {
      cpuFuel: callee ? 100000000n : 10000000000n,
      memoryBytes: callee ? 4194304n : 16777216n,
      wallTimeLimitMillis: 5000n, childCalls: 0, outboundRequests: callee ? 0 : 8,
      stateReadBytes: 0n, stateWriteBytes: 0n,
      blobReadBytes: provider === "blob" ? 65536n : 0n,
      blobWriteBytes: provider === "blob" ? 65536n : 0n,
      logBytes: 0n, effectCount: 0,
    },
  };
}

export function guestU64(response) {
  const success = response.value.success;
  if (!success || success.mediaType !== mediaType || success.payload.length > 128) throw new Error("unexpected-guest-result");
  const result = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(success.payload));
  if (!Array.isArray(result) || result.length !== 1 || typeof result[0] !== "string"
    || !/^(0|[1-9][0-9]{0,19})$/.test(result[0]) || BigInt(result[0]) > 18446744073709551615n) throw new Error("unexpected-guest-result");
  return result[0];
}
