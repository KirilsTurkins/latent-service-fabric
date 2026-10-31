# Rust executor root-drain notification

This is a source-level continuation of the [owned thread checkpoint](rust-owned-thread-source.md)
for [PR #1371](https://github.com/KirilsTurkins/latent-service-fabric/pull/1371).
It does not qualify ordinary ThreadPool execution or close #743 or #689.

## Preserved signed failure

[Signed run 41191812242](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/41191812242)
at source `4785147be33bb460abcdfcc9527d783481ba7ece` authenticated the matched
compiler and native origins, but its first `pools-cold` call returned a guest
fault with no decoded result, 298,549 fuel, 7,795,224 peak memory bytes and zero
effects. Its 116-member artifact `13039200986` is 611,422 bytes with ZIP SHA-256
`e284e8eeea9000de0ddeb52c5d03e3c3e4eee7d3ccf4fd1cb56ee634ccaafdfd`.
The unchanged component is 511,683 bytes with SHA-256
`3948e0fc6d64dbf40914915ba0618f14cdd4a45e6e4762ecf6e0e801fac4f4c6`.

The separate [diagnostic run 41204624424](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/41204624424)
reported `AsyncDeadlock`, one suspended root and no remaining runnable threads
or host futures. That observation does not identify the original wait or prove
that the source defect below is the sole cause of the signed failure. The
normal signed result remains failed; diagnostic builds do not replace it.

## Missing retirement notification

`thread_runtime::drain` scans executor progress, prepares a completion waiter,
then scans again before parking. `executor_root::progress_all` deliberately
returns no completion stamp when a release changes its registry snapshot: a
release callback or destructor may register successor work, so the old snapshot
cannot authorize root completion.

Previously, successful `Releasable` retirement removed the entry and freed its
pool, Control backing and logical Executor without publishing that transition.
If retirement occurred in the second scan, the prepared waiter could remain
unnotified even when the last executor had gone. No worker would remain to
provide the notification needed for the next scan. A previously quiescent
stamp also retained its old epoch across that removal.

The retirement branch now calls the existing `changed()` only after pool
release, physical Control deallocation and Executor settlement. This advances
the existing epoch and notifies the existing completion queue. The current
scan still cannot declare completion; the root must rescan all live entries.
No registry borrow crosses release or notification. There is no replacement
scheduler, unconditional pending-loop wake, new allocation, owner, grant or
increase to the 32 MiB, five-second or eight-Native-owner guest limits.

## Focused controls and evidence boundary

`tests/executor_root_native.rs` compiles the actual `executor_root.rs` and
`runtime_owner.rs`. Five controls cover the last release after wait preparation,
unchanged pending work, invalidation of an old quiescent stamp, a successor
registered by a pool destructor, and captured pool/Control/owner retirement
before notification. The pool uses its real final retained Arc and the Control
uses the actual `SystemOwned` allocation and owner implementation.

The completion sink, host admissions and Control worker methods are explicit
test ports. These controls test the notification/epoch and destruction boundary,
not a canonical suspension, worker TLS semantics or physical Wasmtime retirement.
The existing 29 TLS, wait-driver and synchronization controls remain unchanged.
The existing compiler programme additionally builds, lists and runs exactly
these five tests before sysroot construction, retaining their logs and count.
Its application diagnostic still requires all 76 native library controls.

The compiler-only push trigger now also covers the active runtime branch and
its runtime source paths. Application compilation remains an explicit,
default-false diagnostic choice; a compiler-only success is not a guest result.
All catalogue fixtures, compiler/native provenance pins and five signed-call
assertions remain unchanged. A fresh application compiler observation, reviewed
catalogue/component integration, matched native build and all five successful
signed calls with retirement/accounting witnesses are still required. No new
component identity or successful signed outcome is inferred from this repair.
