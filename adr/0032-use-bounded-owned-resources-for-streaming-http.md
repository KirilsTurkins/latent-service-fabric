# ADR-0032: Use bounded owned resources for streaming HTTP

- **Status:** Accepted
- **Date:** 2026-09-14
- **Delivery:** [#212](https://github.com/KirilsTurkins/latent-service-fabric/issues/212)
- **Extends:** [ADR-0031](0031-version-host-abi-recognition-independently-of-provider-authority.md)

## Context

Current reading: [ADR-0033](0033-use-scoped-durable-local-blobs-with-owned-chunks.md)
selects V4 and adds local blobs. The HTTP resource ownership contract below is
retained by that extension; V3 is the historical profile introduced here.

Buffered byte lists cannot deliver a large response incrementally without
reserving its complete body. HTTP needs a resource lifetime spanning guest calls
while retaining exact destination authority, the accepted activation and finite
memory ownership. Returning a Rust DTO is not proof that canonical lowering has
finished or that the transport has stopped.

## Decision

Select `lsf-host-abi-phase3-v3` as the current generic profile. Preserve all V1/V2
sources and identities. Add exactly `latent:http/streaming@0.3.0` with owned
upload/body/chunk resources, freestanding async operations and the
[streaming contract](../docs/runtime/streaming-http.md). This supersedes
ADR-0031's current-profile selection and initial resource restriction only for
that exact host interface. Public application resource exports, implicit
future/stream types and arbitrary resource identities remain unsupported.

Accept one finite transfer under current policy and required audit at `open`.
Keep its original identity, destination, cumulative byte allowance, deadline and
cancellation ownership through all continuations. Independently charge finite
resident chunks and their lowering copies. A dropped chunk frees resident memory
without refunding transferred bytes. A cancelled waiter cannot refund actual
transport, retained data or resource-table storage.

The initial concrete transport profile uses HTTP/1.1 and identity encoding,
shared bounded DNS/TLS/pools, a single pending upload frame and demand-driven
response reads. Reject compressed responses, upgrades and replay. Treat
redirects as responses requiring a new independently authorized request. Drop
closes actual I/O synchronously and does not wait for network/audit persistence.
A healthy idle connection retains no activation. These are versioned transport
choices; permanent authority, finite ownership and dormancy rules remain intact.

## Consequences

- First-chunk delivery no longer requires complete body buffering.
- Guests must drop chunk/body/upload resources; resource and transfer limits
  reject excess retention before additional I/O.
- Package and runtime compatibility recognize exact named resource identities
  and own/borrow shapes without widening the application value codec.
- Prepared/native identity changes with V3; node/compiler profiles remain paired.
- Fresh Stores, finite cells and no dormant service-owned execution resources
  remain required. This does not add durable effects or stronger tenant isolation.
