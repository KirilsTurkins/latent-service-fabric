<!-- LSF-WIKI-MANAGED -->
# Security and isolation

LSF’s security model is architectural direction plus a narrow Phase 0
containment result. The current spike must not be presented as a production
security boundary.

## Phase 0 protections exercised

The local Wasmtime path applies bounded component size, linear memory, fuel,
wall-clock deadline, log storage, prepared-cache, pool, and queue limits. It
uses epoch interruption for non-cooperative guest work and a fresh store/host
state for every invocation.

The containment suite demonstrates that the tested trap, timeout,
cancellation, fuel, and memory-pressure paths remain activation-local and that
a healthy echo can follow them. If cleanup is not explicitly reusable, the
cell is quarantined.

## Important limits

Phase 0 does not establish:

- tenant authentication, authorization, or identity delegation;
- production capability grants for HTTP, secrets, blobs, state, or events;
- multi-tenant memory/handle isolation guarantees;
- signed artifact admission, provenance verification, or SBOM policy;
- host-process trust sharding, network policy, mTLS, or audit retention; or
- a claim that arbitrary guest code is safe to run in production.

The echo fixture is a locally trusted test artifact. Its successful execution
does not grant trust to a general uploaded capsule.

## Target security rules

The intended design uses WIT-declared imports intersected with deployment and
caller policy. Capability handles are activation-scoped and must be revoked at
cleanup. Stronger blast-radius containment can use a fixed number of
trust-class execution hosts; it must not devolve into a persistent process per
service.

Read the [security architecture](https://github.com/KirilsTurkins/latent-service-fabric/blob/development/docs/architecture/security.md),
[identity and capabilities architecture](https://github.com/KirilsTurkins/latent-service-fabric/blob/development/docs/architecture/identity-and-capabilities.md),
and [SECURITY.md](https://github.com/KirilsTurkins/latent-service-fabric/blob/development/SECURITY.md).
