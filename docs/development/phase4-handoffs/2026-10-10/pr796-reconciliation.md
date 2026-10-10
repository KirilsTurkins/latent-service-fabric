# PR #796 linked retention and recovery reserve

## Issue and integration

PR #796 contributes response-body retirement, linked dispatch protection and
physical recovery admission to
[#397](https://github.com/KirilsTurkins/latent-service-fabric/issues/397).
It closes no issue. The ticket requires complete installed quota, retention,
maintenance, compaction and recovery qualification across twelve acceptance
criteria, including authenticated consuming runtime evidence.

The original feature head is `8f85a60021786138a25f75b8fbc22c32f8789844`.
Normal integration of development `2301d7f0d92c3e3e204a1963f075eef9f776c8e6`
keeps current atomic accounting, retention review, compaction, native custody,
startup retirement, security diagnostics and pinned Go 1.27.2 controls. It does
not replace those implementations with the older feature versions.

## Snapshot decisions

Cleanup #850 and portable continuation #978 preserve the original source and
its earlier evidence. Their 227 source cases and nine native cases qualify
their recorded revisions. They supply context rather than an additional fix
for the current linked-retention tests.

Entity/restore continuation #966 and abandoned-reader checkpoint #957 concern
#398/#399. Current development already includes the delivered receipt and SDK
corrections from #808. The separate restore-reader, actor/Origin and installed
restore qualification work is retained in those checkpoints; it is not imported
into this focused retention change. Full current restore qualification remains
with its owning tickets.

## Retained behavior and CI repair

Recovery compatibility methods validate the constructor's original immutable
partition and submit through the existing fixed workers, physical writer and
retained-resource ledger. They create no new worker or policy authority. Tests
cover full ordinary queues and workers, reserved reads, invalid repartitioning,
oversized jobs, detached waiters and native engine snapshots.

Three real-engine linked dispatcher schedules expire response bodies while
effects are pending, in-flight or uncertain. Reopen preserves original command,
inbox, effect and payload association. Pending delivery remains eligible;
unqualified uncertain redelivery and stale provider receipts remain refused.

The CLI preserves exact recovery identity and 64-bit counters. Dispatcher
transport admission still requires a trusted node operator and administrator
before the runtime is contacted. Java route evidence combines bounded private
reply recording with a sanitized rejection summary through one original call.

The old Rust CI failure occurred in
`detached_revoked_lookup_keeps_original_native_owner_until_actual_provider_cleanup`:
fixture namespace creation encountered `audit-busy` while the new journal worker
first held its control mutex. The isolated fixture now waits for the existing
bounded idle notification before its first management mutation. Production
admission, deadlines and mutation semantics are unchanged; no rejected operation
is retried. Recovery tests likewise observe actual physical retirement before
asserting released capacity.

The old runtime-contract job failed during pinned Clippy installation with a
`bin/cargo-clippy` component conflict, before source execution. The pinned
Rust 1.97.1 compiler and Clippy run successfully in the fresh Linux helper.

## Current validation

On pinned Rust 1.97.1 Linux, all four affected library suites pass:

| Suite | Passed | Existing guarded ignores |
| --- | ---: | ---: |
| latent-state | 245 | 0 |
| latent-commit | 100 | 0 |
| latent-wire | 183 | 23 |
| latent CLI | 157 | 0 |

Compiled test discovery registers all eleven new Rust cases and preserves every
old case and ignore. The historical retention evidence JSON remains unchanged;
it is not a receipt for this integrated source.

Pinned Python 3.13.5 Linux runs all 3,672 maintained cases: 3,654 pass and the
18 existing host/tool guards skip. Both Java evidence cases pass without skips.
CI coverage preserves 88 baseline and 274 current required run blocks and
145 delegated script owners. Foundation, documentation and workspace formatting
checks pass. Ordinary all-target Clippy passes for state, commit and wire;
the original warnings remain in their existing code. Required all-target Clippy
with warnings denied passes for latent, latentd, latent-testkit and
latent-admission. No lint suppression or execution guard is added.

Hosted CI will run after push; delivery does not wait for its completion.
