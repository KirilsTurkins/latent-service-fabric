# Package SBOM profile

Phase 2 begins SBOM support with a deterministic, bounded CycloneDX JSON profile in `latent-packaging`. This foundation is intentionally separate from registry attachment, signature/provenance trust and catalog admission policy, which remain tracked by the later #145/#146 work.

## Supported document profile

- media type: `application/vnd.cyclonedx+json`;
- CycloneDX specification version: `1.6`;
- LSF profile marker: `org.lsf.sbom.profile=lsf-cyclonedx-1`;
- subject kind: exact immutable OCI package manifest identity (`PackageDigest`), not the component-only release digest;
- document bytes are emitted deterministically for identical inputs and receive their own SHA-256 `ArtifactBlobDigest`.

The package subject is recorded twice and both forms must match the caller's expected package digest during inspection:

- the root metadata component `bom-ref` is `urn:lsf:package:<sha256-package-digest>`;
- the root metadata component property `org.lsf.package.digest` contains the canonical package digest.

Inspection accepts only the documented LSF CycloneDX subset. It is deliberately strict rather than silently normalizing unsupported schema variants.

## Inventory input

The generator consumes an explicit `SbomInventory`; it does not execute or inspect guest behavior and does not claim to reconstruct dependency metadata from opaque Wasm bytes.

Entries have one of four roles:

| LSF role | CycloneDX component type | Meaning |
| --- | --- | --- |
| `guest-dependency` | `library` | dependency declared by the guest build inputs |
| `wit-package` | `library` | WIT contract/package input |
| `build-tool` | `application` | compiler, packager or other declared build tool |
| `asset` | `file` | optional non-capsule asset associated with the package |

Each entry may carry a version, source identifier, license expression and exact SHA-256 artifact digest. Source and license attribution are never invented: `org.lsf.source.status` and `org.lsf.license.status` explicitly record `declared` or `unavailable`. Known licenses use the CycloneDX license-expression field.

The generator sorts entries before serialization. Duplicate role/name/version identities are rejected instead of being merged. Names, versions, sources, license expressions, entry count and final document bytes are bounded by `SbomLimits`.

## What this establishes

This slice establishes deterministic generation, exact-byte hashing, strict inspection, subject binding, bounded metadata and explicit unavailable attribution for capsule and asset inventories.

It does **not** yet establish:

- OCI referrer attachment or discovery;
- mandatory-SBOM admission policy;
- publisher, signature or provenance trust;
- vulnerability analysis or an online advisory service;
- proof that an opaque component's dependency or license inventory is complete.

A dependency inventory is evidence about declared build inputs, not a guarantee that the package is vulnerability-free or safe to execute.

## Follow-up boundary

The remaining #145 work must attach and discover these exact bytes through the Phase 2 OCI evidence format and reject missing, conflicting, mismatched or policy-disallowed associations. #146 then integrates verified evidence with catalog admission. Those changes must preserve the exact package subject and document digest produced here rather than reserializing SBOM content at the trust boundary.
