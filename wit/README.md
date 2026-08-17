# WIT contracts

WIT is the authoritative guest-facing contract layer for LSF capsules, platform capabilities, and component-to-component imports/exports.

Each directory is a separately versioned WIT package. The `latent:platform/capsule` world aggregates the initial platform imports available to a capsule after deployment policy has granted them.

The contracts deliberately use opaque activation-scoped handle identifiers where the exact Component Model resource representation remains an open implementation decision.
