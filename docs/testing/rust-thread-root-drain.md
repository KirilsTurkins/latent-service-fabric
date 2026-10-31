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
The original 29 TLS, wait-driver and synchronization test names and assertions
are retained. The existing compiler programme additionally builds, lists and
runs exactly these five root tests before sysroot construction, retaining their
logs and count. Its application diagnostic still requires all 76 native library
controls before owner success.

The early-notification wait-driver control now also exercises the actual
executor-root registry, affine Owner, fixed wait registry, WaitQueue and driver
together. It adopts the reviewed Source-port regression from diagnostic source
`0d6a9269e9c079aae6ee9cbe5c888f8398769de2`, without any diagnostic node or engine
instrumentation. A pool becomes releasable after the root prepares its waiter;
its final Arc destructor deliberately emits no notification. The exact host-call
sequence must contain neither canonical suspension nor resume-later, and a
fresh empty-registry scan plus original owner and wait retirement are required.
A test-only suspension callback prevents a broken implementation from hanging,
but any use of that callback fails the exact sequence assertion. All eleven
wait-driver test names and their existing assertions remain. The Source-port
pool does not claim captured-executor or signed-runtime coverage.

[Diagnostic run 41217651378](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/41217651378)
passed that one selected early-notification test at source
`ae3bbddf554dfa47febcab025fb6a3ceacef070b`; ten other wait-driver tests were
filtered out in that diagnostic. Its overall failure and unchanged retained
guest are not reclassified. The normal compiler owner runs all eleven tests,
including this integrated subcase, alongside the five separate root controls.

## Application-mode validation on the runtime branch

The push trigger covers the active runtime branch, runtime sources, the existing
application compiler and the native catalogue. On
`feat/rust-thread-runtime-20261023` pushes, the existing bounded owner selects
application compilation and its mandatory controls. The older compiler-input
branch remains compiler-only on push. Manual `workflow_dispatch` keeps the
explicit `application-diagnostic` input default false. The same selector guards
all application prerequisites and the compiler command; no second runner or
alternate qualification path is introduced. Permissions remain read-only,
and deadlines, source/artifact bounds and all runtime gates are unchanged.

[Application run 41218846793](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/41218846793)
at exact source `b610bf2490db57a95f4f7b5c087b660b76dd6fd9` passed all 34 native
controls and the emitted result/private-dispatch engine controls, rebuilt the
repaired owned sysroot, and compiled the unchanged ordinary application. Its
116-member artifact `13048229653` is 52,700,826 bytes with ZIP SHA-256
`4ca49ad27759facd7f5c8796884b1fecd8ce93f5a70cc1f678b53c91528cb732`.
The 239-entry source inventory identifies that exact source. All ZIP member
CRCs and the archive digest were checked after download.

The actual original core is 261,403 bytes, SHA-256
`8cd26a5f34ec90f23af43dfcb21b0b619b369ed2199a5368a24572bb96cbf177`.
Its retained object observation has 1,221 matched definitions (463 function,
758 data) and 5,246 relocation edges, with no unresolved referents, matching
failures or instruction-decode failures. This is one additional direct-call
relocation compared with the prior 5,245-edge graph. The original
`executor_root::progress_all` body is now 1,407 bytes with SHA-256
`abda2353bdcb03540fb1039fdcf1d7b1f16215e0e6ccfa56d8d6b69d37bdcb93`.
These are actual retained compiler facts, not a promoted trusted catalogue.

The old immutable native catalogue refused `rust-original-full-body-or-signature`
before normal-component encoding. The owner failed at that boundary; its
application-mode 76 library controls were not reached. No normal component was
produced, no guest ran, and no signed outcome passed. Catalogue fixtures,
compiler/native provenance pins and all five signed-call assertions remain
unchanged. A reviewed catalogue/component integration, matched native build,
and five successful signed calls with retirement/accounting witnesses remain
required. Development-branch merge conflicts are not resolved by this compiler
observation or the regression integration.
