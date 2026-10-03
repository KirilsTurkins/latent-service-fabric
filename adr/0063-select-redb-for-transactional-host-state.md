# ADR-0063: Select redb for transactional host state

- Status: Accepted for the bounded first-engine profile
- Date: 2026-09-30
- Owner: [#381](https://github.com/KirilsTurkins/latent-service-fabric/issues/381)
- Contract: [#380](https://github.com/KirilsTurkins/latent-service-fabric/issues/380)

## Decision

Use redb **4.3.0**, pinned exactly, for one node-owned state/command/outbox
database. Closed family tags share one physical transaction. Guest bindings
receive host-scoped views and staged changes, never engine objects, paths or a
second database. The implementation belongs behind `latent-state`; command and
effect semantics remain in `latent-commit` and `latent-effects`.

The review used the [exact upstream release](https://github.com/cberner/redb/releases/tag/v4.3.0)
and its [source and manifest](https://github.com/cberner/redb/tree/v4.3.0).
The selected default `std` build uses MIT OR Apache-2.0 licensing, needs Rust 1.90
or newer and fits this repository's pinned Rust/MSRV. Experimental multiprocess
features and optional adapters are disabled. Set the page cache explicitly to
8 MiB; the upstream default is unsuitable for the bounded node profile.

| Requirement | redb 4.3.0 decision | SQLite alternative |
| --- | --- | --- |
| Atomic families, snapshots, conflicts | One database transaction; old read views; host validates expected rows and namespace generation before commit | Transactions/read snapshots work; host still owns OCC and command semantics |
| Flush and uncertain outcomes | `Durability::Immediate`; failed commit quarantines the owner and requires original-key recovery after retirement/reopen | WAL plus synchronous FULL needs an independently qualified connection/checkpoint policy |
| Filesystem owner | One protected descriptor, exclusive writer lock, bounded cache | Database, WAL and shared-memory sidecars need coupled protected ownership |
| Backup/compaction | Qualified closed-store backup and compaction with no live read view; no online-copy claim | Online backup/checkpoint APIs exist but would need a second ownership implementation |
| Evolution/corruption | Versioned LSF marker; reject unknown/corrupt bytes without reset; redb recovery remains engine-owned | Explicit schema migrations and corruption reporting are possible |
| Dependencies | One pinned Rust engine; no SQL parser or C build in runtime | Adds SQLite/C build or system-library closure, without a current SQL requirement |

SQLite was considered, not selected or added to the runtime. The available Python
3.13.5 comparison tool embeds [SQLite 3.49.1](https://www.sqlite.org/releaselog/3_49_1.html);
that version is disclosed rather than presented as current production support.
Review of [WAL ownership and checkpoints](https://www.sqlite.org/wal.html) and
[synchronous settings](https://www.sqlite.org/pragma.html#pragma_synchronous)
informed the choice. WAL still has one writer, checkpoint progress can be held
by readers, and WAL is unsuitable for a network filesystem. This is a dependency
and owner-complexity choice, not a claim that SQLite lacks transactions or is
slower. No SQLite benchmark or supported second backend was delivered.

## Selected physical profile

Use an existing private protected node root on a Linux x86-64 local filesystem.
The node retains one descriptor/database owner, one fixed write worker and a
finite queue (8 requests). Up to 8 read views share the same database and have a
30-second logical lifetime. Cache is 8 MiB, keys at most 1 KiB by default, values
at most 1 MiB, batches at most 256 mutations/checks each, and the default logical
store at most 16,384 rows/32 MiB. Constructors impose absolute ceilings.
The protected root, physical disk accounting, queue admission, cancellation
drain and owner quarantine are implemented/qualified by #383. These bounds are
the handoff contract, not proof that an arbitrary caller of the prototype is a
qualified production node owner. Guest execution never holds an exclusive
writer transaction. A cancelled waiter does not retire accepted physical I/O.

The integrated [protected store owner](../docs/development/shared-state-store-owner.md)
uses three fixed workers (two native readers and one writer), with eight queued
and 32 accepted jobs. Its internal framed keys/values allow 4 KiB/2 MiB and
1,024 checks or mutations per batch, so complete atomic envelopes fit the same
transaction. Guest key/value limits remain 1 KiB/1 MiB. The prototype defaults
above remain unchanged. The [integrated results](../docs/evidence/transaction-store-owner-381.json)
exercise this physical boundary; complete node and distribution qualification
remain later handoffs.

Normal writes use immediate durability. Validation/conflict/quota failures
before commit abort every family. A failed commit is **uncertain**, never a
proven business abort: the in-memory store stops new operations, keeps physical
ownership, and later recovery inspects the original command identity. Do not
rerun a guest, invent a new command or delete its pending effects. Disk-full,
permission loss, corrupt/unsupported formats and repair failure must fail closed;
the engine's allocator repair is not permission to reset application records.

The [repeatable qualification](../docs/testing/transaction-store-engine.md)
records finite real commits, two concurrent writers, retained/expired read views,
compaction, closed backup/reopen and owned child termination before/after commit.
The local Docker volume exposes the WSL2 Linux ext filesystem. Measurements are
observations under that virtualized host load, not throughput promises.
Process-crash checks establish all-or-none recovery at those barriers;
they do not establish power-loss behavior, arbitrary storage hardware safety,
network/shared-writer support or production-store readiness.

## Consequences and follow-up

Do not invent a journal/WAL, expose SQL/engine APIs to a guest or create a pool
per tenant. Preserve one implementation and one set of transactions for every
guest language. #384 scopes namespaces; #385 enforces snapshot/OCC/phantom and
ABA semantics; #386 commits complete command receipts/results/effects/inbox;
#387 owns durable command admission. #390/#391 retain effect authority and
attempt ownership. #397/#399 govern linked retention and restore clocks.
The six guest compilers and final #405 packaging gate consume this engine through
the host; they are distinct from this first-engine qualification decision.
