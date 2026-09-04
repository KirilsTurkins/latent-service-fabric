# Manifest codec and Phase 1 admission contract

Status: Phase 1 normative contract for issue #3.

## Responsibilities

`latent-manifest` exposes two independent layers:

1. `JsonManifestCodec` accepts or produces bytes. It applies bounded JSON
   preflight before collection allocation, rejects duplicate object keys,
   retains JSON numeric values with arbitrary decimal precision, canonicalizes
   every number by mathematical value, validates the decoded value against the
   canonical schema embedded from `schemas/`, converts it to the Rust domain
   model, and normalizes values used for indexing.
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
| Entries in one JSON array or object | 4,096 |
| Collected schema violations | 128 |

`ManifestLimits` makes every parser limit explicit. A recursive streaming Serde
visitor checks each collection before the wire decoder constructs a complete
`Vec` or map. It retains only the bounded set of keys for the object currently
being visited so duplicate keys can be rejected without allocating the decoded
value tree. The authoritative schemas independently retain a 4,096-entry
maximum for manifest arrays and open objects; increasing a caller's parser
envelope therefore does not widen the current wire contract.

Payload and string bounds are byte bounds, not Unicode character counts. A
parser-limit failure produces exactly one root violation. Malformed UTF-8,
malformed JSON, trailing JSON values, duplicate keys, and over-limit nested
collections are errors. No decoder API panics for untrusted bytes.

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

Every open object and every array nested below trigger configuration is subject
to the same schema and parser cardinality ceiling. Trigger configuration is
retained without numeric precision loss but normalized to canonical JSON values;
it is not interpreted by Phase 1. Duplicate keys are rejected even inside open
objects.

## Draft 2020-12 numeric semantics

`latent-manifest` enables `serde_json`'s `arbitrary_precision` representation.
Every accepted number retains its exact mathematical decimal value rather than
being routed through binary `f64`. This includes integers wider than `u64`,
high-precision fractions, and finite JSON number lexemes such as `1e400` and
`1e-400` under recursively nested trigger configuration.

Schema type `integer` is mathematical rather than lexical. Consequently `1`,
`1.0`, `1e0`, and `-0.0` are integer values, while `10000.5` and values such as
`1.0000000000000000000000000000000001` are not. Every valid numeric token is
normalized before schema validation and model construction: redundant leading
and trailing zeroes are removed, negative zero becomes zero, exponent casing,
signs, and leading zeroes are normalized, and mathematically equivalent
significand/exponent combinations converge to one representation.

Canonical numbers use plain decimal notation when the normalized decimal point
lies in the compact range from `1e-6` through values below `1e21`; values outside
that range use scientific notation with one leading significant digit, a
lowercase `e`, and an explicit exponent sign. This keeps extreme exponents
compact instead of expanding them into proportional runs of zeroes. Integral
values inside the `i64`/`u64` JSON integer envelope are emitted as ordinary
integer tokens so typed deserialization remains exact.

Minimum and maximum checks use normalized decimal comparison rather than
binary floating-point conversion. Numeric equality used by `const`, `enum`,
and `uniqueItems` follows the same mathematical rule. A shared regression
corpus is loaded with exact decimal values and run through both the Rust
evaluator and Python's full Draft 2020-12 validator in CI.

## Canonical encoding

`encode_*` returns compact UTF-8 JSON with stable property ordering and no
insignificant whitespace. Before encoding, the codec:

- lowercases hexadecimal release digests;
- sorts capsule exports and imports;
- sorts deployment grants, grant operations, and placement set fields;
- recursively orders keys in arbitrary trigger configuration objects;
- uses ordered maps for metadata and constraints;
- emits typed integer values in canonical integer form;
- emits every arbitrary-precision trigger number in the value-canonical form
  described above, without rounding or exponent expansion;
- omits an absent `wallTimeLimitMillis`, retaining its `None` meaning.

The codec never deduplicates an invalid list: semantic or schema validation
reports the duplicate. JSON array order is preserved where the schema does not
define a set-like field. Canonical bytes are suitable as deterministic local
indexing input; cryptographic artifact identity remains the separately declared
release digest.

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
sorted and deduplicated by the stable `(path, code)` identity before return.
Callers may rely on `path` and `code`; `message` is diagnostic text and may
improve without an API revision. When schema and model guards identify the same
failure, the schema diagnostic is retained once.

Paths use a JSONPath-like form rooted at `$`, for example
`$.spec.resources.wallTimeLimitMillis` and `$.imports[1].contract`. Codes use
lower-kebab-case, including `malformed-json`, `duplicate-key`,
`collection-limit-exceeded`, `unknown-field`, `invalid-type`,
`unsupported-api-version`, `invalid-digest`, `unsupported-state-model`,
`invalid-stateless-budget`, `tenant-scope-mismatch`, and
`budget-exceeds-capsule`.
