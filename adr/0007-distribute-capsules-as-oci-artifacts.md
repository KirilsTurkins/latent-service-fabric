# ADR-0007: Distribute capsules as OCI artifacts

- **Status:** Accepted
- **Date:** 2026-08-17

## Context

LSF needs content addressing, existing registries, signatures, attestations, and SBOM association.

## Decision

Package capsule layers and metadata as OCI artifacts identified by digest.

## Consequences

Registry behavior remains behind `ArtifactRepository` and `OciRegistry` interfaces.
