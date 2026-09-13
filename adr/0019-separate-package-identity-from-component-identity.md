# ADR-0019: Separate package identity from component identity

- **Status:** Accepted
- **Date:** 2026-09-11
- **Delivery:** Phase 2 foundation, [#140](https://github.com/KirilsTurkins/latent-service-fabric/issues/140)

## Context

Phase 1 `ReleaseDigest` identifies component bytes. Its locally trusted catalog
completion record separately protects the immutable manifest and typed contract
metadata. An OCI manifest identifies a larger graph: configuration, component,
contracts and other layers. Signing only the component digest would leave a
different package with the same component outside that signature's identity.

## Decision

Introduce strict `PackageDigest` and `ArtifactBlobDigest` identities. Each accepts
only `sha256:` followed by 64 lowercase hexadecimal characters. Preserve the
existing `ReleaseDigest`, capability `BlobDigest`, local records, RPCs and SDK
contracts. There is no implicit conversion from component to package identity.

Use the OCI image manifest envelope for a documented, bounded LSF artifact
profile. Package identity hashes the exact received manifest bytes. Configuration
and every layer have independent exact-byte digests and lengths. Deterministic
publishing uses the LSF canonical encoding profile; decoding does not hash a
normalized reconstruction in place of the received bytes.

Package kinds distinguish executable capsules from browser assets and opaque SSR
renderer packages. The last two are packaging formats only. Neither is accepted
as an executable capsule by this contract. File names are bounded portable
logical paths, with collision and traversal checks before any materialization.

Signature, provenance and SBOM artifacts use separate manifests whose `subject`
names the immutable package. They do not become recursively embedded in the
package they describe. OCI referrer discovery only establishes an association;
the later verification implementations must authenticate the payload's subject,
publisher or builder and policy independently.

The [format specification](../docs/protocol/package-format.md) defines the wire
contract, bounds and migration behavior. Registry transfer, signing, policy
admission and runtime adoption remain separate Phase 2 deliveries.

## Consequences

- Existing locally trusted publications remain byte-identical and usable. They
  do not acquire signed-package trust merely by being re-opened.
- Packaging the same component with changed metadata produces a different
  package identity. Existing immutable metadata conflicts remain conflicts;
  package import must define its catalog association explicitly.
- Shared content addressing does not authorize cross-tenant discovery or access.
  Catalog admission and queries retain authenticated tenant checks.
- Raw package parsing creates no guest instance, execution cell or permanent
  service resource. Document, graph and content limits remain explicit.
- The current OCI/signing interface return and subject types change before their
  concrete implementations are introduced. Existing invocation SDK wire
  identities remain component identities; no protocol field is reinterpreted.

## References

The separate packaging, evidence, admission and runtime deliveries described in
this decision are now complete. Their identities remain distinct; see the
[Phase 2 completion map](../docs/phase-2-completion.md) for the implemented
composition and its finite validation.

- [OCI image manifest 1.1.1](https://github.com/opencontainers/image-spec/blob/v1.1.1/manifest.md)
- [OCI content descriptors 1.1.1](https://github.com/opencontainers/image-spec/blob/v1.1.1/descriptor.md)
- [OCI distribution decision](0007-distribute-capsules-as-oci-artifacts.md)
- [Phase 1 local catalog](../docs/development/local-release-catalog.md)
