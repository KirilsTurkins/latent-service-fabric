# Declarative resource schemas

These JSON Schemas define the versioned external shape of capsule, deployment,
locally trusted release-publish, binding, policy, trigger, and compiled route
documents, plus the Phase 2 package format.

The schemas are the wire-format authority. `latent-manifest` embeds the capsule,
deployment, binding, policy, and trigger schemas and evaluates them before a
JSON value can enter a typed manifest model. Any model/schema divergence must
be resolved in favor of the schema or recorded as an API-versioned schema
change.

The capsule's closed optional runtime/target/CPU requirements are described in
[release compatibility](../docs/reference/release-compatibility.md). Schema
success checks their shape; actual host support and structural old/candidate
comparison require the corresponding Rust checks.

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
| [build-observation.schema.json](build-observation.schema.json) | Unsigned bounded observation of a committed-source echo build. |
| [package-provenance-statement.schema.json](package-provenance-statement.schema.json) | Restricted in-toto statement binding exact package/component identities and build observations. |
| [package-provenance.schema.json](package-provenance.schema.json) | Closed single-signature DSSE provenance envelope. |
| [builder-policy.schema.json](builder-policy.schema.json) | Explicit builder anchors and source requirements, separate from publisher policy. |
| [builder-revocations.schema.json](builder-revocations.schema.json) | Expiring builder revocations bound to one canonical builder policy. |
| [package-sbom-inputs.schema.json](package-sbom-inputs.schema.json) | Normalized declared/observed package inputs for deterministic SBOM generation. |
| [package-sbom.schema.json](package-sbom.schema.json) | Closed CycloneDX 1.6 profile embedded before package identity is computed. |
| [package-sbom-policy.schema.json](package-sbom-policy.schema.json) | Explicit embedded/detached presence and per-role attribution requirements. |
| [package-admission-upload.schema.json](package-admission-upload.schema.json) | Closed JSON projection of authenticated package publication and exact evidence bytes. |
| [package-admission-receipt.schema.json](package-admission-receipt.schema.json) | Bounded historical admission identities and policy generations; never an executable grant. |
| [supply-chain-policy.schema.json](supply-chain-policy.schema.json) | Complete approved publisher/builder/revocation/SBOM snapshots and tenant authorization. |
| [node-supply-chain.schema.json](node-supply-chain.schema.json) | Standalone `supplyChain` member selecting local compatibility or enforced admission. |

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
canonical policy identity, freshness, revocation and owner limits. The
[build provenance profile](../docs/reference/build-provenance.md) separately
authenticates builder assertions and exact source/component/package associations.
Its byte bounds, timestamp ordering, duplicate material names, cross-field digest
equality and current authority also require the Rust API. Synthetic schema
fixtures confer no trust. [Final catalog admission](../docs/reference/package-admission.md)
composes these format/evidence checks under current node-owned authority,
durable clock/generation floors and guarded publication/execution boundaries.

The [SBOM profile](../docs/component-development/sbom.md) binds exact inventory
bytes through a reserved package layer and checks identical detached associations.
The pinned [offline upstream schemas](../tools/data/cyclonedx-1.6/README.md)
provide an additional interoperability check. Source/path rules, unique property
names and identities, SPDX parsing, cross-field digest associations and content
policy also require the Rust APIs. Authenticating the exact package binds its
embedded inventory; standalone referrer presence confers no publisher authority.

The [packaging workflow](../docs/component-development/packaging.md) validates
supplied components against the pinned WIT graph and typed contracts. Recipe
schema checks are separate from filesystem confinement and semantic validation.
