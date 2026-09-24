# ADR-0007: Distribute capsules as OCI artifacts

- **Status:** Accepted
- **Date:** 2026-08-17

## Current implementation

Bounded authenticated OCI transfer, exact package/evidence association and
current supply-chain admission are delivered. See the
[registry profiles](../docs/reference/oci-registry.md) and
[network profile](../docs/reference/oci-network-profile.md) for supported TLS,
credential, DNS, redirect and referrer behavior. Registry possession alone does not
authorize a publisher or permit execution.

## Context

LSF needs content addressing, existing registries, signatures, attestations, and SBOM association.

## Decision

Package capsule layers and metadata as OCI artifacts identified by digest.

## Consequences

Registry behavior remains behind `ArtifactRepository` and `OciRegistry` interfaces.
