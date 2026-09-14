# Blob model

Phase 3 implements the guest blob capability through configured Linux
[local](../runtime/local-blobs.md) and [S3](../runtime/s3-blobs.md) providers.
Both use the exact `latent:blob/blob@0.2.0` interface, tenant-scoped immutable
references, finite staging and owned read chunks. Their shared capability port
is separate from the package repository and raw artifact cache delivered in
Phase 2. Standalone provider composition remains #226; cluster replication and
cross-node transfer remain later work. See the
[capability surface](../runtime/capabilities.md) and [roadmap](../roadmap.md).

Large payloads should not be repeatedly serialized through the router, runtime, and component call graph. The implemented guest model represents them as immutable content-addressed blob references.

## Write lifecycle

```text
begin staged write
  → bounded sequential chunks
  → digest and size verification
  → seal immutable blob
  → return a tenant-scoped immutable reference
```

A failed or expired write cannot issue a successful reference without verified seal evidence. Local stages are reclaimable under their retained owners. An S3 operation may have an uncertain remote outcome; its durable cleanup inventory remains charged until explicit reconciliation establishes a valid receipt or safe retirement.

## Read lifecycle

The capability broker binds each reader to its original tenant and activation. Every read rechecks operation authority, cumulative byte budgets and the original deadline. A returned chunk owns its prepaid host bytes and one canonical guest copy until release. The local provider pins the verified file; S3 pins a durable version receipt and verifies aligned part hashes before disclosure. Neither exposes unrestricted host pointers. Shared-memory and cross-node transfer profiles remain future work.

## Ownership and retention

A guest reference identifies its exact SHA-256, size and media type; the current tenant and configured provider namespace determine its authority. Retention, pinning, replication, and garbage collection are platform concerns independent of capsule execution lifetime.
