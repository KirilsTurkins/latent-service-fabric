# Rust ThreadPool root-retirement wakeup investigation

This is a source repair candidate, not a signed runtime qualification. The
ordinary Rust builder, immutable compiler catalogue, runtime grants, five-call
campaign and original nonempty fault-frame assertion remain unchanged.

## Retained observation

[Diagnostic run 41211537571](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/41211537571)
ran at `6bfe565fb78324f8e503bddfdb0ad23b8dd465b0`. All five source/version,
native numeric-control and diagnostic-node build command records succeeded.
The original `pools-cold` call still failed with typed trap 22 (`AsyncDeadlock`),
without the original fault backtrace required by the existing diagnostic gate.
The independent suspension observation does not satisfy that gate.

Artifact `13047236011` is 42,061,197 ZIP bytes, with SHA-256
`f576fb099597818a75fe171750197be6e1f08741a2b97f1380f4f42943494f9d`.
Its unchanged component is 511,683 bytes, with SHA-256
`3948e0fc6d64dbf40914915ba0618f14cdd4a45e6e4762ecf6e0e801fac4f4c6`.
The new diagnostic node is 200,557,680 bytes, with SHA-256
`f9a7da7ed2bf493693428ceaf6c8d9a951dfbda35e19b72634e9a650bbd2273d`.
The four historical helper identities are not relabelled as new builds.

The last-root-suspension record visited six frames in five raw traversal steps.
No truncation, missing-coordinate, unmapped-frame or unavailable-transfer flag
was set. All frames have observation-local module ordinal zero. The complete
eight-slot scheduler prefix contained one suspended thread and one host root,
with no other thread states counted, empty high/low queues and an exhausted
host-future stream. This describes the final observation, not the absence of
previous guest progress or proof of successful physical retirement.

## Coordinate attribution

The retained compiler materials are artifact `13038776169` from
[compiler run 41189829966](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/41189829966),
source `e3f0edf822c10e84bbeede276174ac3217542afc`, with ZIP SHA-256
`c3dcc608d605de8b07fffbfa6bdbc15d78311253107cc5d752cb448c7bfdbaf7`.
The executed component's main core is 245,836 bytes, with SHA-256
`93caf2abc959b644491ddf44294242ce56dace0f8c447543768096d484e1e28f`.
Its payload starts at component byte 703. Do not use the component-relative
`moduleOffset` as an offset into the extracted standalone core: subtract 703.
For every row below, the component-relative coordinate equals 703 plus that
core function's body start plus the observed function offset.

| Ordinal | Function | Component offset | Function offset | Reviewed source location |
| --- | --- | --- | --- | --- |
| 0 | 288 | 76700 | 500 | `wait_driver::drive_wait`, call to original `[thread-suspend]` |
| 1 | 449 | 132337 | 44 | `Wait::wait`, call to `drive_wait` |
| 2 | 240 | 58505 | 284 | `runtime::drain`, completion-queue wait |
| 3 | 357 | 89350 | 104 | `finish_stacked_thread_tls`, indirect drain callback |
| 4 | 376 | 93025 | 63 | `__lsf_rust_root_finish`, TLS cleanup call |
| 5 | 63 | 16666 | 176 | retained greeting application, root-finish call |

These source labels are review annotations, not strings emitted by the runtime
observer or an authentication mechanism. Numeric coordinates and the exact
component/compiler inputs remain distinct from the source-level diagnosis.

## Missed-wakeup repair

`runtime::drain` checks executor progress, prepares a waiter on the original
completion queue, and checks again before waiting. `executor_root::progress_all`
requires a stable registry snapshot before returning a completion stamp. When
its second check releases the final executor, removing that entry necessarily
invalidates the snapshot, so it returns `None`. Previously, this removal did
not publish `changed()`. If the pool destructor emits no independent event and
no worker remains, the prepared waiter can suspend with nobody left to wake it.

The repair publishes `changed()` after the actual pool release callback,
Control backing drop and Executor owner settlement. It holds no registry borrow
across the notification, grants no resource, creates no extra owner, and does
not return success from the invalidated snapshot. The notified waiter instead
performs the existing fresh progress and retirement checks. This is a concrete
source-level missed-wakeup path consistent with the captured cleanup wait;
repaired signed guest execution is still required to establish its effect on
the observed component failure.

## Native regression and hosted result

The existing native early-notification control now also includes the actual
executor-root registry, affine Owner, WaitQueue, fixed wait registry and wait
driver. Its explicit Source-port pool is pending at the first check and becomes
releasable after the waiter is prepared. Its final release callback deliberately
does not notify. The control checks pool-value destruction, owner settlement,
absence of canonical suspension/resume, complete waiter retirement and a fresh
stable empty-registry stamp. A bounded fallback notification lets the unfixed
case return, but the exact call sequence rejects that spurious suspension.
This is not a captured-executor, canonical-engine or signed-component test.

The diagnostic programme builds and runs that exact source-bound native
control before rebuilding the node. Its recipe includes every participating
SDK source; the retained guest is not rebuilt or replaced by this check. The
normal compiler-input programme also continues to run the existing eleven
wait-driver tests, with this regression added to the early-notification case.

[Diagnostic run 41217651378](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/41217651378)
at `ae3bbddf554dfa47febcab025fb6a3ceacef070b` compiled, listed and passed the
selected native early-notification control (one passed, ten filtered out).
Its numeric native control also passed, and all eight source/version,
control-build/list/run and diagnostic-node build command records exited zero.
Artifact `13048683583` is 44,114,000 ZIP bytes with SHA-256
`0626c2215842c5e9929404182c6f7844f011d8ca2f9198ad2a95c82ea1a85fe7`.
Independent download verified the archive digest, all 136 member CRCs and the
sizes and hashes of all sixteen retained build-command log streams.

The retained `build/root-retirement-wakeup-control` executable is 7,491,664
bytes with SHA-256
`292d87a63194d7fb9fc16e8254f2d510e8b75af09aefc27c7e50b639010dfdd0`.
A separate local execution of that exact hosted-built binary listed all eleven
wait-driver controls and passed all eleven with `--test-threads=1`, with no
ignored or filtered tests. This was not a local Rust compilation, a pre-fix
native mutation test, or a signed guest execution.

The diagnostic run as a whole still failed on the unchanged original guest.
Its diagnostic node is 200,557,680 bytes with SHA-256
`a976d4b3090129e0c7a95f9f7ad613993a752ce19b821d922798d1ce4ea6c6bb`.
The same component again produced trap 22 and the same six suspension frames,
with 298,549 fuel, 7,795,408 peak memory bytes, no decoded result and zero
effects. The repaired SDK was exercised by the native control, not compiled
into this frozen guest; that repeated failure is not a repaired-guest result.
The original nonempty fault-frame gate remains unsatisfied and mandatory.

## Suspension-record parser ordering

The observer emits its suspension header before every associated frame. The
parser now rejects frames preceding that header instead of allowing a later
header to adopt earlier orphan frames. The existing numeric/privacy control
covers both wholly reversed records and a single earlier orphan, plus the six
actual retained coordinates, CRLF input and private-text exclusion. A suspension
record alone still cannot create `numeric-fault-frames.json` or qualify runtime
progress. Existing case IDs, range checks and failed-transfer controls remain.

Isolated parser validation with the fetched production helper definitions
reproduced exactly the two ordering failures in the old parser. The corrected
parser passed all 44 negative subtests and the positive assertions. This is
not a claim that the complete repository test suite or current-head CI passed.

## Remaining proof

The repaired owned sysroot and unchanged application still need a new compiler
observation, reviewed immutable catalogue update, matching native products and
the original signed five-call campaign. Historical receipts and the current
failed result must not be rewritten to stand in for that work. Integration
conflicts and other CI failures remain separate obligations.
