# Declarative resource schemas

These JSON Schemas define the versioned external shape of capsule, deployment,
locally trusted release-publish, binding, policy, trigger, and compiled route
documents.

The schemas are the wire-format authority. `latent-manifest` embeds the capsule,
deployment, binding, policy, and trigger schemas and evaluates them before a
JSON value can enter a typed manifest model. Any model/schema divergence must
be resolved in favor of the schema or recorded as an API-versioned schema
change.

Unknown structural fields are intentionally rejected. Open-ended data is
limited to the objects explicitly marked by a schema: metadata maps,
capability-grant constraints, and trigger configuration. Manifest arrays and
open objects are capped at 4,096 entries, including arrays and objects nested
recursively inside trigger configuration. Integer fields use Draft 2020-12
mathematical integer semantics and include explicit maxima matching their Rust
wire types.

See `docs/protocol/manifest-codec.md` for parser limits, normalization, semantic
Phase 1 validation, and forward-compatibility rules.
