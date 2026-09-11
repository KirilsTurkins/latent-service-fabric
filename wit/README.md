# WIT contracts

WIT is the authoritative guest-facing contract layer for LSF capsules, platform capabilities, and component-to-component imports/exports.

Each directory is a separately versioned WIT package. The `latent:platform/capsule` world aggregates the platform contract surface across phases; declaring or granting an import does not make a provider available.

The completed Phase 1 runtime supports `latent:context/context`, `latent:log/log`,
`latent:clock/monotonic`, and `latent:clock/wall`. Other capability families remain
later-phase contracts and are rejected during preparation. See the
[capability reference](../docs/runtime/capabilities.md) and
[supported synchronous value mapping](../docs/protocol/wit-values.md).

The contracts deliberately use opaque activation-scoped handle identifiers where the exact Component Model resource representation remains an open implementation decision.
