# Transaction store engine qualification

The first-engine decision is [ADR-0061](../../adr/0063-select-redb-for-transactional-host-state.md).
It qualifies the bounded storage prototype, not the complete Phase 4 node.
The [recorded result](../evidence/transaction-store-engine-381.json) preserves
the actual source snapshot, engine/tool/configuration and host observations.

Run the existing Rust owner, on the supported Linux local-volume profile:

```sh
cargo test -p latent-state --lib embedded::tests --locked -- --nocapture
cargo clippy -p latent-state --all-targets --locked -- -D warnings
```

The source-matched suite inventory includes every new case. The process-crash
test uses the existing `latent-testkit` owned process and output limits. It
terminates and reaps a child at the pre-commit and post-commit barriers, then
reopens the same database and checks state, command and outbox together. A
test-only barrier never enters a product build. Corrupt bytes and concurrent
file ownership are rejected without truncation/reset. A stale expected row or
one-over row quota changes no family. Old snapshots stay coherent; expired
views refuse further reads while their physical pin remains owned until drop.

The finite workload performs 32 immediate commits, a writer while a snapshot
is retained, a conflicting batch, compaction after view retirement, a closed
backup plus file sync, and reopening. Two fixed concurrent workers separately
prove one winning commit/one conflict and preservation of independent rows.
The measurement's short view lifetime is a controlled test value, not the
default production handoff. The resource probe reports actual Linux `/proc`
observations; Windows probes leave unavailable fields absent.

Use a unique disposable private directory or owned Docker volume. Remove only
that fixture after every process/database owner retires; preserve failed logs
and the original database for diagnosis. Do not run against a deployment root,
reset corrupt bytes, copy a live database, share a writer over a network mount,
or infer production qualification from a portable Windows run. The tests do not
simulate disk-full or actual power interruption; #383 and the later native
distribution qualification own those additional boundaries.
