# Phase 2 package identity and artifact format

This is the format foundation delivered by
[#140](https://github.com/KirilsTurkins/latent-service-fabric/issues/140). It
defines bounded models, codecs and validation. The
[packaging workflow](../component-development/packaging.md) adds deterministic
build/inspection and component/WIT checks. The [registry adapter](../reference/oci-registry.md)
adds scoped authenticated transfers. [Publisher signature verification](../reference/publisher-trust.md)
binds exact packages to approved keys and current trust state. Provenance/SBOM
verification, trusted catalog admission and rollout remain subsequent tickets in the
[Phase 2 epic](https://github.com/KirilsTurkins/latent-service-fabric/issues/139).

## Identity and compatibility

| Identity | Bytes or object identified |
| --- | --- |
| `ReleaseDigest` | Existing Phase 1 component bytes; local catalog and invocation RPC meaning is unchanged. |
| `PackageDigest` | Exact OCI package manifest bytes, including their configuration/layer descriptors. |
| `ArtifactBlobDigest` | Exact configuration, layer or other content bytes. |
| Implementation version | Package's declared semantic version; it is not a content identity. |
| WIT version | Contract package version, independent of the implementation version. |
| Revision/generation | Existing deployment policy and publication identities; see [routing](../deployment-routing.md). |

New digest types require lowercase SHA-256 syntax. They cannot be implicitly
constructed from `ReleaseDigest`. Hashing a parsed-and-reserialized remote
manifest would identify different bytes: retain and hash its exact input.
Whitespace or ordering changes may therefore create distinct valid package
digests. Canonical publishing is deterministic but does not relabel received
content.

No migration rewrites Phase 1 catalog keys, completion records, historical
receipts, RPC descriptors or SDK invocation fields. A future verified importer
must persist the association between package and component identity, enforce
existing metadata immutability, and derive trust from verified evidence. An old
local record is not evidence of a signed package. Deduplicating bytes never
grants another tenant authority to discover, deploy or inspect them.

## Package envelope

The envelope uses `schemaVersion: 2` and
`mediaType: application/vnd.oci.image.manifest.v1+json`. Its required fields are
`schemaVersion`, `mediaType`, `artifactType`, `config`, `layers` and `annotations`.
Unknown structural fields are rejected by the LSF execution profile. This is a
narrow package consumer, not a claim that generic OCI registries reject unknown
artifact types.

| Kind | `artifactType` | Required content |
| --- | --- | --- |
| `capsule` | `application/vnd.latent.capsule.v1` | One component, capsule manifest, typed contracts and WIT lock graph; optional assets. |
| `browser-assets` | `application/vnd.latent.browser-assets.v1` | Asset layers only. |
| `ssr-package` | `application/vnd.latent.ssr-package.v1` | One opaque renderer plus optional assets. |

The configuration descriptor has exactly `mediaType`, `digest` and `size`, with
media type `application/vnd.latent.package.config.v1+json`. A layer descriptor
adds `annotations` containing exactly `org.opencontainers.image.title` (logical
path) and `dev.latent.layer.role`. No external descriptor URL or inline data is
accepted by this profile. No archive extraction or automatic URL fetch occurs.

## Configuration and layers

Configuration fields are `formatVersion: 1`, `kind`, `name`, `version`,
`entrypoint`, `layers` and `annotations`. A capsule also requires
`componentDigest`; other kinds forbid it. Each configuration layer contains
exactly `path`, `role`, `mediaType`, `digest` and `size`.

The configuration's layer list and envelope's layer list must correspond exactly
in path, order, role, media type, digest and length. Paths are strictly sorted by
ASCII byte order. The capsule's component digest equals its component layer
digest. Its entrypoint names that component. Browser and SSR entrypoints name an
asset or renderer respectively. The configuration annotations and capsule
manifest carry package configuration metadata; these are not deployment secret
values or an authority to override operator policy.

| Role | Media type |
| --- | --- |
| `component` | `application/wasm` |
| `capsule-manifest` | `application/vnd.latent.capsule.manifest.v1+json` |
| `contracts` | `application/vnd.latent.contracts.v1+json` |
| `wit-lock` | `application/vnd.latent.wit-lock.v1+json` |
| `asset` | Bounded base MIME type, without parameters. |
| `renderer` | `application/wasm` or `text/javascript` |

Format validation is not a proof that opaque Wasm exports match the supplied
contracts, that an SSR runtime is available, or that a publisher is trusted.
Those checks belong to packaging, compatibility and admission. Asset and SSR
packages cannot pass the capsule-kind check merely by containing Wasm bytes.

## WIT source lock graph

The `wit-lock` layer is a closed JSON document with required `formatVersion: 1`,
`world`, `contractsDigest` and `packages` fields. `contractsDigest` names the
exact typed-contract metadata layer bytes. Every package entry requires `id`,
`sourcePath`, `digest` and `dependencies`.

`id` is a pinned `namespace:package@version`; `world` is
`namespace:package/world@version`. Identifiers begin with a lowercase ASCII
letter, end with an alphanumeric character, and otherwise contain lowercase
letters, digits or hyphens. Each identifier segment and version is at most 128
bytes; each complete package/world identity is at most 512 bytes. Versions use
SemVer. Package entries are strictly sorted by ID; each dependency list is
strictly sorted and unique. All referenced dependencies and the world's package
must exist, and cycles are rejected. Package and per-package dependency counts
are bounded by the layer-count ceiling.

Each `sourcePath` names a distinct `asset` layer with media type `text/plain`.
Its digest names the exact UTF-8 WIT source bytes, with no implicit newline or
source normalization. `validate_wit_lock` checks those layer associations and the
contracts digest. Raw source content must also pass the normal byte length/hash
verification. Packaging subsequently parses WIT, verifies declared package and
dependency identities, and checks agreement with the compiled component and
typed contracts. A self-consistent lock graph alone is not that semantic proof.

## Evidence association

Detached evidence is another OCI manifest with a required `subject` descriptor
containing the package manifest's media type, exact package digest and length.
It uses the OCI empty configuration: media type
`application/vnd.oci.empty.v1+json`, the SHA-256 of the two ASCII bytes `{}`, and
size `2`. Exactly one evidence layer has title and role annotations; its role is
`evidence`.

| Evidence | Artifact type | Layer media type |
| --- | --- | --- |
| Signature | `application/vnd.latent.signature.v1` | `application/vnd.latent.signature.payload.v1+json` |
| Provenance | `application/vnd.latent.provenance.v1` | `application/vnd.latent.provenance.payload.v1+json` |
| SBOM | `application/vnd.latent.sbom.v1` | `application/vnd.latent.sbom.payload.v1+json` |

These envelope types define subject associations. The
[publisher signature profile](../reference/publisher-trust.md) defines the
implemented signature payload and verification policy. The
[build provenance profile](../reference/build-provenance.md) separately defines
authenticated builder assertions and exact source constraints. SBOM payload
verification remains a subsequent ticket. A referrer with a matching
subject alone is not authenticated.
Required evidence must pass independent subject, integrity and trust checks
before admission. Evidence cannot be made part of the same manifest it signs;
that would create a digest cycle.

## Bounds and portable names

The codec defaults are also its hard ceilings. A caller may lower them.

| Resource | Ceiling |
| --- | --- |
| JSON document | 256 KiB |
| JSON nesting | 16 |
| JSON nodes | 16,384 |
| JSON string | 4,096 UTF-8 bytes |
| Package layers | 256 |
| Annotations per map | 32 |
| Individual layer | 64 MiB |
| Aggregate layer content | 256 MiB, using checked arithmetic |
| Logical path | 240 ASCII bytes; 64 per segment |
| Package name/version | 128 bytes each |
| MIME type | 128 ASCII bytes |
| Annotation key | 128 ASCII bytes |

Names use lowercase ASCII alphanumeric characters with interior `.`, `_` or
`-`. Versions use SemVer. Paths allow only ASCII letters, digits, `.`, `_`, `-`
and `/`, with no absolute path, empty/`.`/`..` segment, trailing dot, Windows
reserved basename, case-insensitive collision or file/directory prefix collision.
Backslashes, colons, percent encoding, query strings and fragments are rejected.
MIME tokens use lowercase ASCII letters, digits, `.`, `_`, `+` and `-`, with an
alphanumeric first character in both type and subtype. Annotation keys use ASCII
letters, digits, `.`, `_`, `-` and `/`; keys cannot be empty. Annotation values
have the string byte ceiling and cannot contain control characters.

The decoder rejects duplicate keys, unknown fields, excessive nesting/counts
and malformed integer tokens before accepting a typed value. Wire integers are
nonnegative integer tokens representable as `u64`; fractional/exponent spellings
do not acquire an integer field's authority through rounding. JSON Schema alone
cannot express all byte, lexical, cross-layer and graph constraints; the Rust
codec enforces those additional requirements.

## Deterministic encoding

LSF publishing emits compact UTF-8 JSON without a trailing newline, using fixed
model field order, sorted annotation keys and strictly path-sorted layers.
Optional capsule identity is omitted for other kinds. Numeric fields emit decimal
integers. JSON strings use the codec's JSON escaping rules. This is the versioned
LSF encoding profile, not a claim of RFC 8785/JCS conformance.

Golden examples and adversarial fixtures exercise the schemas and codec. The
package graph validator checks exact configuration/descriptor associations;
content verification additionally compares each available blob's exact length
and SHA-256. No digest, successful parse or well-formed descriptor alone grants
publisher trust or creates execution resources.

See [ADR-0019](../../adr/0019-separate-package-identity-from-component-identity.md),
the [OCI manifest specification](https://github.com/opencontainers/image-spec/blob/v1.1.1/manifest.md)
and [content descriptor specification](https://github.com/opencontainers/image-spec/blob/v1.1.1/descriptor.md).

## Focused validation

With the pinned toolchain and Python development dependencies installed:

```sh
cargo test -p latent-core digest --locked
cargo test -p latent-core --doc --locked
cargo test -p latent-artifacts --test package_format --test package_adversarial --test package_golden --locked
cargo test -p latent-artifacts --lib package::wit_lock --locked
cargo test -p latent-oci --locked
python -m unittest discover -s tools/tests -p test_package_format.py
```

These portable format checks do not select the Linux catalog durability suite,
instantiate guests, contact a registry or run a load campaign. Normal Linux CI
also checks the existing workspace, SDKs and runtime invariants before merge.
