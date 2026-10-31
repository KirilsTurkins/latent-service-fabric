# Durable publication retention pins

## Delivery boundary

This is the native storage foundation for issue #662, not the completed
committed-publication deletion feature. The repository exposes trusted-host
pin/unpin and original-operation lookup APIs. There is no operator pin/deletion
CLI or public management transport in this change. Committed publications,
including retired and revoked publications, still retain their content. Existing
orphan reclamation is unchanged; do not manually remove catalog files.

A pin is **negative retention authority only**. It neither grants execution or
HTTP serving nor restores an expired, revoked or retired release. Generation
changes do not discard a pin. Clearing a pin does not authorize deletion.

## Exact bounded mutation

An authenticated host adapter must authorize the caller's scope and actor before
calling `publication_retention_snapshot` or `change_publication_retention`.
Supplying a tenant ID, operation ID, historical receipt or fence is not
credentials. The repository checks exact publication scope, expected generation,
and an opaque catalog fence covering lifecycle, componentless-web and retention
heads. Each installation receives an independent random retention identity;
copying equivalent publication bytes into another installation does not recreate
a fence. A complete stopped backup intentionally preserves that identity.

A request has one original operation ID and 1–32 strictly ordered, distinct
publication targets. The shared owner admits at most 1,024 current pins and 64
retained operation receipts, with separate byte ceilings (64 KiB per request,
4 MiB per head, and 4 MiB plus 4 KiB per intent). Encoding enforces its byte bound
while writing. A zero-allocation lexical prepass bounds nesting to 16 levels,
encoded strings to 4 KiB, and structural delimiters to 131,072 before typed
decoding. Canonical re-encoding and schema checks remain mandatory. The caller supplies a positive deadline of at most 30 seconds;
checks bracket bounded work and durability boundaries. Filesystem calls cannot
be forcibly cancelled: the shared owner and charges remain held until physical
I/O retires. There is no per-publication task, timer, collector or directory scan
on a pin batch.

The mandatory preflight callback runs outside reference/commit fences. A host
adapter must reserve required audit and response capacity there. All original
preconditions are rechecked after that callback and before the durable intent.
A publication or retention change during preflight refuses the stale request.
This callback contract is not an implemented management/audit integration.

## Persistence and original-operation recovery

The catalog stores a bounded checksummed `HEAD`, original-operation `INTENT` and
`INITIALIZED` record under `lifecycle/retention`. Before accepting the first pin
intent it durably promotes `LIFECYCLE_MODE` to
`lsf-release-lifecycle-retention-v1`. Older readers reject that marker before
cleanup. Do not downgrade or rewrite it. Checksums detect corruption; they are
not signatures or protection against an owner rewriting the whole installation.

The write sequence is intent file sync and parent sync, new head file sync and
parent sync, then intent unlink and parent sync. Only after the final sync is
memory/accounting adopted. An uncertain write poisons this incarnation's
lifecycle and web authority. Preserve the installation, stop its owner, reopen
with a compatible reader, and query the **original** operation ID. Reopen may
finish only the exact validated durable intent; it never invents a replacement
request. Incomplete format promotion with no intent does not invent a pin.

`Found` returns the original receipt, not current serving/rollback eligibility.
`Unknown` includes finite receipt eviction and proves neither nonexecution nor
permission to replay. A retained identical request returns its receipt; changing
its fields conflicts. An evicted original fence cannot silently apply again
because every successful mutation advances retention state. There is no retry
loop. Malformed, missing protected, foreign-mode or unsupported retention state
is refused before ordinary temporary cleanup.

## Accounting and backup

`PublicationStorageSnapshot.retention_control_bytes` includes conservative head,
intent and atomic-write exposure, not just currently allocated filesystem blocks.
It contributes to the existing storage limit and remaining capacity; conservative
metadata exposure contributes to the existing index limit. Pins do not refund
publication files or shared blobs. Shrinking pin metadata is accounted only after
the new durable head and intent-removal parent synchronization.

A backup is the **complete stopped installation**, including root markers,
`lifecycle`, `web`, committed publication directories, shared content and the
coupled protected control/audit stores. Preserve permissions and hard links.
Never copy just a retention head into another catalog. Restore using compatible
readers with the original protected authority; restoring an older installation
is not permission to replay external effects or unknown administrative mutations.
The native test here copies a stopped publication catalog and preserves inode
sharing, pins, receipts and terminal eligibility. It is not qualification of an
online backup or of the still-unimplemented deletion/tombstone lifecycle.

Admission evidence, trust/revocation history and administrative audit have their
own owners and retention rules. Pin receipts neither replace audit nor permit
pruning any of those histories. This foundation does not change their retention.

## Native qualification and remaining issue scope

Run the registered Linux host suite with the exact source and the explicit
`development-test-host` fault-injection feature:

```sh
cargo test --locked -p latent-artifacts --all-features \
  --test publication_retention -- --nocapture --test-threads=1
cargo test --locked -p latent-artifacts --all-features --lib
```

The integration target uses actual `DirectoryArtifactRepository` files, locks,
rename, unlink and filesystem synchronization. Injected boundary failures are
not claims of power-loss testing. The componentless-web fixture injects a
non-cryptographic host authority; it does not qualify signature policy. Suite
registration alone is not execution evidence.

Issue #662 still requires the deletion/tombstone protocol; persistent deployment,
HTTP-trigger and rollout target protection; reader/preparation race qualification;
last-reference payload unlink/sync/refund; authenticated CLI and finite audit
integration; deletion backup/restore; and source-bound native deletion/release
sequence measurements. None are marked complete by this pin foundation.
