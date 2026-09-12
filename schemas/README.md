# Declarative resource schemas

These JSON Schemas define the versioned external shape of capsule, deployment,
locally trusted release-publish, binding, policy, trigger, and compiled route
documents, plus the Phase 2 package format.

The schemas are the wire-format authority. `latent-manifest` embeds the capsule,
deployment, binding, policy, and trigger schemas and evaluates them before a
JSON value can enter a typed manifest model. Any model/schema divergence must
be resolved in favor of the schema or recorded as an API-versioned schema
change.

Unknown structural fields are intentionally rejected. For Phase 1 manifests,
open-ended data is
limited to the objects explicitly marked by a schema: metadata maps,
capability-grant constraints, and trigger configuration. Manifest arrays and
open objects are capped at 4,096 entries, including arrays and objects nested
recursively inside trigger configuration. Integer fields use Draft 2020-12
mathematical integer semantics and include explicit maxima matching their Rust
wire types. Arbitrary trigger-configuration numbers are retained with exact
decimal significand and exponent precision; they are never silently rounded
through binary floating point.

See the [manifest codec contract](../docs/protocol/manifest-codec.md) for parser limits, normalization, semantic
Phase 1 validation, and forward-compatibility rules.

The package schemas describe a separate immutable artifact format:

| Schema | Document |
| --- | --- |
| [package-config.schema.json](package-config.schema.json) | Capsule, browser asset or SSR configuration and content descriptors. |
| [package-manifest.schema.json](package-manifest.schema.json) | OCI package envelope referencing exact configuration and layer bytes. |
| [package-evidence.schema.json](package-evidence.schema.json) | Detached signature, provenance or SBOM association with an exact package subject. |
| [package-wit-lock.schema.json](package-wit-lock.schema.json) | Pinned WIT source package identities, dependencies and content digests. |
| [package-source.schema.json](package-source.schema.json) | Explicit bounded file-selection recipe for deterministic packaging. |
| [package-build-inputs.schema.json](package-build-inputs.schema.json) | Packager receipt associating observed input identities with exact output layers. |
| [package-signature.schema.json](package-signature.schema.json) | Closed single-signature LSF envelope using DSSE PAE. |
| [package-signature-claims.schema.json](package-signature-claims.schema.json) | Exact signed package subject, publisher claim and validity interval. |
| [publisher-policy.schema.json](publisher-policy.schema.json) | Explicit bounded publisher-key approval policy. |
| [publisher-revocations.schema.json](publisher-revocations.schema.json) | Explicit expiring revocations bound to one exact canonical policy. |

These schemas close structural objects, enforce role/media-type combinations,
and bound arrays, names and annotations. Package annotations permit at most 32
string entries. The package codec additionally enforces raw document and UTF-8
byte limits, duplicate-key rejection, integer token spelling, total content
size, sorted collision-free paths, exact descriptor associations, entrypoints,
and WIT dependency graph rules. JSON Schema validation alone does not establish
those properties. Its mathematical integer semantics cannot distinguish `1`
from `1.0` or `1e0`; the package wire parser rejects the latter spellings.

See the [package format contract](../docs/protocol/package-format.md) and its
[small exact-byte fixtures](../examples/package-format/README.md). Successful
format validation does not establish publisher trust, payload semantic
compatibility, registry availability or executable guest content. The signature
schemas describe the implemented [publisher trust profile](../docs/reference/publisher-trust.md).
Its Rust verifier additionally checks cryptography, exact subject association,
canonical policy identity, freshness, revocation and owner limits. Provenance and
SBOM payload authentication remain subsequent Phase 2 features.

The [packaging workflow](../docs/component-development/packaging.md) validates
supplied components against the pinned WIT graph and typed contracts. Recipe
schema checks are separate from filesystem confinement and semantic validation.
