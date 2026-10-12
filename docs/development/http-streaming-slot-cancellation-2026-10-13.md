# Streaming HTTP cancellation reservation repair

`open` reserves an upload slot before awaiting its real connection future, and
`read` reserves a chunk slot before awaiting body I/O. Previously, cancellation
destroyed the transport future but could leave an unpublished, empty slot
unavailable for subsequent operations in the same Store.

An affine reservation now holds that exact slot identity through the actual
future lifetime. The `Reserved` field order destroys its transport/body value
before making the unpublished slot reusable. The slot records a sticky published
bit, including during borrows, so a late guard cannot erase a published resource,
borrowed handle or newly reused id. Borrowed bodies/uploads remain caller-owned
until their existing canonical drop/abort; separately held chunks stay charged.
Guard metadata keeps the original table-memory reservation alive if it outlives
the table. The capacity remains 64 and the existing permission, deadline,
provider, memory and chunk ceilings are unchanged.

Five focused native table controls passed, including 65 actual pending TCP
cancellations and fresh slot reuse for each reservation kind, transport-before-
rollback ordering, and published/borrowed/stale-id protection. All nine existing
real-provider streaming HTTP integration tests passed, including suspended guest
read cancellation and physical socket/resource cleanup. The actual library list
retains all 356 prior cases and both ignored collectors, adding precisely the
three new controls (359 total). Foundation and CI command coverage passed.
Check-only Clippy completed with 42 warnings in existing source; its only warning
in these files concerns the unchanged `Value` enum. No warning allowance changed.

The [retained packet](../testing/evidence/http-streaming-slot-cancellation-2026-10-13.json)
binds the exact source and frozen native test products. Failed setup attempts and
the intervening disk/Docker failure remain in local evidence. This independently
attributable host repair changes no TypeScript profile or public application
world and does not establish installed fetch qualification. The separate SDK
retirement bridge and signed within-activation borrowed-read/cancel/drop controls
remain required before that claim.
