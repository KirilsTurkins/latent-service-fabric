# WIT contracts

WIT is the authoritative guest-facing contract layer for LSF capsules, platform capabilities, and component-to-component imports/exports.

Each directory is a separately versioned WIT package. The `latent:platform/capsule` world aggregates the platform contract surface across phases; declaring or granting an import does not make a provider available.

The completed Phase 1/2 runtime supports `latent:context/context`, `latent:log/log`,
`latent:clock/monotonic`, and `latent:clock/wall`. Phase 3 adds explicitly configured local-service, buffered HTTP and streaming
HTTP adapters. Remaining capability families require their own providers and
are rejected during preparation when unavailable. Phase 2 package
and trust support does not install those providers or expand the supported ABI.
See the
[capability reference](../docs/runtime/capabilities.md) and
[supported synchronous value mapping](../docs/protocol/wit-values.md).

The V3 aggregate at `runtime-phase3-streaming` adds exact owned upload/body/chunk
resources in `latent:http/streaming@0.3.0`; both earlier aggregates remain
available. Other contracts may still use opaque activation-scoped identifiers.
See the [current host ABI matrix](../docs/runtime/host-abi-profile.md) and
[streaming resource contract](../docs/runtime/streaming-http.md).
