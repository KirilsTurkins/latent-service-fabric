# ADR-0007: Distribute capsules as OCI artifacts

- **Status:** Accepted
- **Date:** 2026-08-17

## Implementation status at Phase 1 completion

OCI registry push/pull and associated supply-chain integration are Phase 2 work. Phase 1 delivers verified local artifact/release catalogs.

## Implementation status at Phase 2 completion

Bounded authenticated OCI transfer, exact package/evidence association and
current supply-chain admission are delivered. See the
[registry profile](../docs/reference/oci-registry.md) for supported TLS,
credential and referrer behavior and the [completion report](../docs/phase-2-completion.md)
for the real-registry and offline validation. Registry possession alone does not
authorize a publisher or permit execution.

## Context

LSF needs content addressing, existing registries, signatures, attestations, and SBOM association.

## Decision

Package capsule layers and metadata as OCI artifacts identified by digest.

## Consequences

Registry behavior remains behind `ArtifactRepository` and `OciRegistry` interfaces.
