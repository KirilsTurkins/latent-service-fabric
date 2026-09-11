# ADR-0007: Distribute capsules as OCI artifacts

- **Status:** Accepted
- **Date:** 2026-08-17

## Implementation status at Phase 1 completion

OCI registry push/pull and associated supply-chain integration are Phase 2 work. Phase 1 delivers verified local artifact/release catalogs.

## Context

LSF needs content addressing, existing registries, signatures, attestations, and SBOM association.

## Decision

Package capsule layers and metadata as OCI artifacts identified by digest.

## Consequences

Registry behavior remains behind `ArtifactRepository` and `OciRegistry` interfaces.
