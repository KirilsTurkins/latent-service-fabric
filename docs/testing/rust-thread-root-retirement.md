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

## Regression and remaining proof

The existing native early-notification control now also includes the actual
executor-root registry, affine Owner, WaitQueue, fixed wait registry and wait
driver. Its explicit Source-port pool is pending at the first check and becomes
releasable after the waiter is prepared. Its final release callback deliberately
does not notify. The control checks pool-value destruction, owner settlement,
absence of canonical suspension/resume, complete waiter retirement and a fresh
stable empty-registry stamp. A bounded fallback notification lets the unfixed
case return, but the exact call sequence rejects that spurious suspension.
This is not a captured-executor, canonical-engine or signed-component test.

The diagnostic programme now builds and runs that exact source-bound native
control before rebuilding the node. Its recipe includes every participating
SDK source; the retained guest is not rebuilt or replaced by this check. The
normal compiler-input programme also continues to run the existing eleven
wait-driver tests, with this regression added to the early-notification case.

At this source checkpoint the new native regression has not yet been executed;
its next hosted result must be retained rather than inferred from review.
After native controls pass, the repaired owned sysroot and unchanged application
need a new compiler observation, reviewed immutable catalogue update, matching
native products and the original signed five-call campaign. Historical receipts
and the current failed result must not be rewritten to stand in for that work.
