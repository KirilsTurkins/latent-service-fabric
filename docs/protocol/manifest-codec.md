# Manifest codec and Phase 1 admission contract

Status: Phase 1 normative contract for issue #3.

## Responsibilities

`latent-manifest` exposes two independent layers:

1. `JsonManifestCodec` accepts or produces bytes. It applies bounded JSON
   parsing, rejects duplicate object keys, validates the decoded value against
   the canonical schema embedded from `schemas/`, converts it to the Rust
   domain model, and normalizes values used for indexing.
2. `Phase1ManifestValidator` accepts Rust domain values. It enforces the
   cross-field standalone Phase 1 rules that JSON Schema cannot express. It
   does not read files, persist state, fetch artifacts, compile routes, or
   execute components.

Admission code must run both layers. Structural decoding alone intentionally
accepts schema-valid future-phase capsules such as the checked-in transactional
counter example; semantic Phase 1 validation rejects their unsupported state
model with a stable violation.

```rust
use latent_manifest::{
    JsonManifestCodec, ManifestCodec, ManifestValidator,
    Phase1ManifestValidator,
};

let capsule = JsonManifestCodec::default().decode_capsule(bytes)?;
Phase1ManifestValidator::new().validate_capsule(&capsule)?;
```

Capsule and deployment validation are pure operations over bytes and model
values and can be used by a CLI, control API, local catalog, or tests without an
application binary or storage adapter.

## Supported resource documents

The codec fully maps `Capsule` and `Deployment` documents required by Phase 1.
It also losslessly maps `Binding`, all trigger kinds, and `Policy` documents so
those contracts can evolve before their runtime behavior is implemented.
Release-publish requests and compiled route snapshots remain API/persistence
artifacts rather than manifest models; their checked-in examples continue to
be validated directly against their schemas by `tools/validate_repository.py`.

For deployment, binding, trigger, and policy documents, `metadata.name` is the
single JSON identity and is copied into the typed domain `id`. Encoding a model
whose `id` differs from `metadata.name` fails with `identity-mismatch` rather
than silently losing one identity.

## Parser limits

The default codec applies these limits before model allocation:

| Limit | Default |
| --- | ---: |
| Complete JSON payload | 1 MiB |
| Object/array nesting depth | 64 |
| Encoded bytes in one JSON string | 256 KiB |
| Collected schema violations | 128 |

`ManifestLimits` makes every limit explicit and allows a caller to choose a
smaller envelope. The payload and string bounds are byte bounds, not Unicode
character counts. A parser-limit failure produces exactly one root violation.
Malformed UTF-8, malformed JSON, trailing JSON values, and duplicate keys are
errors. No decoder API panics for untrusted bytes.

## Schema and forward-compatibility policy

The files under `schemas/` remain the wire authority and are compiled into the
crate with `include_str!`; runtime validation therefore has no file-system race
or deployment-time schema lookup. CI also checks every schema with a full Draft
2020-12 validator and validates every mapped example.

Unknown structural fields are rejected (`additionalProperties: false`). A new
field therefore requires a new compatible schema/API revision and an updated
Rust model; old nodes do not silently ignore meaning they cannot enforce. The
only intentional open objects in the current contracts are:

- metadata labels and annotations, whose values are strings;
- capability-grant constraints, whose values are strings;
- trigger `spec.configuration`, whose values may be arbitrary bounded JSON.

The trigger configuration object is retained losslessly but is not interpreted
by Phase 1. Duplicate keys are rejected even inside open objects.

## Canonical encoding

`encode_*` returns compact UTF-8 JSON with stable property ordering and no
insignificant whitespace. Before encoding, the codec:

- lowercases hexadecimal release digests;
- sorts capsule exports and imports;
- sorts deployment grants, grant operations, and placement set fields;
- recursively orders keys in arbitrary trigger configuration objects;
- uses ordered maps for metadata and constraints;
- omits an absent `wallTimeLimitMillis`, retaining its `None` meaning.

The codec never deduplicates an invalid list: semantic validation reports the
duplicate. JSON array order is preserved where the schema does not define a
set-like field. Canonical bytes are suitable as deterministic local indexing
input; cryptographic artifact identity remains the separately declared release
digest.

## Hardened budget meaning

Every numeric budget value is exact. Zero means no grant and is valid; it never
requests a default. `wallTimeLimitMillis` is a relative duration applied from
admission:

- missing or `null` becomes `None` (no wall-time constraint at that layer);
- `0` becomes `Some(0)` (no wall time is granted);
- a positive value is a finite relative ceiling.

`wallDeadlineUnixMillis` and every other absolute-deadline spelling are unknown
fields and are rejected. Persistent manifests therefore cannot retain a stale
absolute instant as a reusable budget. When a deployment is validated against
a capsule, an absent deployment wall-time ceiling is wider than a finite
capsule ceiling and is rejected; equal or smaller relative durations are
accepted.

Standalone Phase 1 admits only stateless Wasm Components. State read/write
budgets must consequently be zero in both capsule and deployment resources.
Other zero-valued resource dimensions remain valid exact denials.

## Semantic Phase 1 rules

The validator enforces at least the following:

- exact `latent.dev/v1alpha1` API version;
- canonical bounded ASCII resource identifiers and versioned contract IDs;
- `sha256:` plus 64 hexadecimal characters for release digests;
- Semantic Version 2.0.0 component and minimum-fabric versions;
- minimum fabric version no newer than the Phase 1 contract version `0.1.0`;
- `wasm-component` backend and `stateless` state model;
- nonzero call-depth bounds;
- route weight in `1..=10000`;
- explicit tenant scope for deployment, binding, trigger, and policy resources;
- namespace only with a tenant, and matching tenant-qualified service IDs;
- unique exports, imports, grants, operations, and placement set fields;
- availability zones no greater than cached copies;
- deployment service, digest, scope, capability imports, and every resource
  ceiling compatible with the referenced capsule.

## Violations

All public operations return `Result<T, Vec<ManifestViolation>>`. Violations are
sorted and deduplicated before return. Callers may rely on `path` and `code`;
`message` is diagnostic text and may improve without an API revision.

Paths use a JSONPath-like form rooted at `$`, for example
`$.spec.resources.wallTimeLimitMillis` and `$.imports[1].contract`. Codes use
lower-kebab-case, including `malformed-json`, `duplicate-key`, `unknown-field`,
`invalid-type`, `unsupported-api-version`, `invalid-digest`,
`unsupported-state-model`, `invalid-stateless-budget`,
`tenant-scope-mismatch`, and `budget-exceeds-capsule`.
