# Declarative resource schemas

These JSON Schemas define the versioned external shape of capsule, deployment,
locally trusted release-publish, binding, policy, trigger, and compiled route
documents, plus the completed Phase 2 package/evidence, trust, lifecycle, native
cache, audit and rollout configuration surfaces. General Phase 3 provider and
web-serving behavior is not established by a schema declaration.

The schemas are the wire-format authority. `latent-manifest` embeds the capsule,
deployment, binding, policy, and trigger schemas and evaluates them before a
JSON value can enter a typed manifest model. Any model/schema divergence must
be resolved in favor of the schema or recorded as an API-versioned schema
change.

The capsule's closed optional runtime/target/CPU/renderer requirements are described in
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

Optional standalone node members have their own closed schemas:

| Schema | Configuration member |
| --- | --- |
| [node-renderer-profile.schema.json](node-renderer-profile.schema.json) | `rendererProfile`: optional closed Angular engine shape; separate from security selection and resource grants. |
| [node-http-ingress.schema.json](node-http-ingress.schema.json) | Optional shared HTTP/TLS listener, explicit principal/proxy adapters and finite connection/exchange deadlines and reservations. |
| [node-isolated-aot.schema.json](node-isolated-aot.schema.json) | `isolatedAot`: bounded native compiler/cache configuration and protected host-key path. |
| [node-audit.schema.json](node-audit.schema.json) | `audit`: optional durable audit resource limits. |
| [node-rollouts.schema.json](node-rollouts.schema.json) | `rollouts`: shared coordinator and optional canary observation limits, requiring the same enabled audit owner. |
| [rollout-canary-policy.schema.json](rollout-canary-policy.schema.json) | Explicit immutable observation duration, candidate sample minimum and outcome/latency thresholds; never evidence of health. |
| [capability-policy.schema.json](capability-policy.schema.json) | Closed exact capability policy v1; required scopes default deny and matching allow ceilings intersect. |
| [capability-provider-binding.schema.json](capability-provider-binding.schema.json) | Tenant-scoped provider profile/configuration identity and additional narrowing; no credentials or installation authority. |
| [capability-policy-resource.schema.json](capability-policy-resource.schema.json) | Typed descriptive target for authenticated policy explanation, never proof of an actual provider destination. |
| [capability-policy-config.schema.json](capability-policy-config.schema.json) | Optional Linux node policy-owner configuration and finite retention/control/read limits. |

The node decoder additionally rejects duplicate members and explicit null
enablement. Runtime derivation checks cross-field resource relationships and
startup binds actual owners. See the [standalone node guide](../docs/reference/standalone-node.md).

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
| [web-application.schema.json](web-application.schema.json) | Closed public asset, route and exact renderer associations inside a browser/SSR package. |
| [web-build-observation.schema.json](web-build-observation.schema.json) | Explicit supplied-file web assembly assertions without synthetic component identity. |
| [web-provenance-statement.schema.json](web-provenance-statement.schema.json) | Separately versioned web provenance binding a complete package and ordered output descriptors. |
| [web-admission-receipt.schema.json](web-admission-receipt.schema.json) | Historical componentless admission through the shared publisher/builder/SBOM authority. |
| [supply-chain-policy.schema.json](supply-chain-policy.schema.json) | Complete approved publisher/builder/revocation/SBOM snapshots and tenant authorization. |
| [node-supply-chain.schema.json](node-supply-chain.schema.json) | Standalone `supplyChain` member selecting local compatibility or enforced admission. |
| [node-isolated-aot.schema.json](node-isolated-aot.schema.json) | Opt-in standalone `isolatedAot` member selecting an approved isolated compiler, protected local key and bounded native caches. |
| [node-audit.schema.json](node-audit.schema.json) | Opt-in standalone `audit` member selecting the durable journal and finite retention, queue and query-owner bounds. |
| [release-lifecycle-record.schema.json](release-lifecycle-record.schema.json) | Canonical durable lifecycle state with exact scope/content and historical actor. |
| [release-operation-receipt.schema.json](release-operation-receipt.schema.json) | Canonical bounded mutation/rejected-attempt receipt; absence does not prove rollback. |
| [release-lifecycle-api.schema.json](release-lifecycle-api.schema.json) | Named closed Protobuf JSON projections for lifecycle queries, mutations and evidence renewal. |

[Lifecycle storage](../docs/reference/release-lifecycle.md#bounds-and-serialization)
uses integer generations and explicit nullable optional fields. Its Protobuf JSON
projection uses decimal-string `uint64` and omitted optional fields; these are
distinct representations. Neither a stored receipt nor a schema-valid API status
is an execution capability. No new JSON listener or CLI command is implied.

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
