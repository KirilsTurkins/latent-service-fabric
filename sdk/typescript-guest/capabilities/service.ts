import * as raw from 'latent:service/invoke@0.1.0';
export type { Target, CallOptions, InvocationOutcome, InvocationResult, DeclaredError, PlatformError }
  from 'latent:service/invoke@0.1.0';
/** Preserve success, application-declared error and platform failure as distinct outcomes. */
export function call(target: raw.Target, payload: Uint8Array, mediaType: string, options: raw.CallOptions) {
  return raw.call(target, payload, mediaType, options);
}
