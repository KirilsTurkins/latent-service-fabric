# Go synchronization qualification

Issue #742's synchronization and retirement matrix has a separate finite
reference through the existing `go-component-activation-v5` compiler/runtime.
The fixture is ordinary Go using `sync`, `sync/atomic`, channels and `time`.
It supplies no LSF API, explicit yield, executor or replacement synchronization
implementation. The maintained runtime, component compiler and original ledger
remain unchanged.

The reference follows the standard [sync API](https://pkg.go.dev/sync) and
[Go memory model](https://go.dev/ref/mem). `Cond.Wait` releases and reacquires its
lock; protected predicates remain in loops. Once publication is observed after
`Do`, and a panicking initializer is not run again. Channel close preserves
buffered values and publication, while a nil select case remains disabled.
The RWMutex control establishes reader/writer exclusion and publication; it
does not invent a particular scheduling order between racing lock requests.

| Mode | Actual ordinary source obligation |
| --- | --- |
| 0 | Two parked condition waiters observe protected state after Broadcast. |
| 1 | A writer excludes two original readers and later readers see its value. |
| 2 | Once waiters progress while its initializer is parked; one initializer publishes to all. |
| 3 | The original Once panic is recoverable and marks the initializer done. |
| 4 | Buffered channel values survive close; closed/nil select cases and publication are preserved. |
| 5 | Signal releases one predicate waiter; Broadcast releases the remaining waiter. |
| 6 | An exported result waits for accepted condition work and a real later timer/Broadcast. |
| 7 | An unknown permanently blocked condition waiter cannot become managed idle. |
| 8 | The original cancellation/deadline wins while condition work and a timer remain accepted. |
| 9 | Atomic spin-loop work permits an eligible sibling to publish without application Gosched. |

The positive fixture keeps the previous v5 test ceiling of16 tasks, including
eight prepaid maintenance reservations, and four waits. A narrower10-task
control must refuse application admission. Each successful invocation observes
physical Store/backend retirement before another fresh Store runs. These are
finite same-tenant controls, not a complete cross-tenant or native-cost matrix.

The identical ordinary source is also compiled with the existing v1 profile
without compiler checkpoints. Under the existing5,000,000-fuel negative bound,
the channel/startup control must first succeed; then the atomic sibling case
must exhaust fuel rather than receive progress credit. A fresh invocation must
succeed afterward. This negative does not alter the positive budget or treat
fuel termination as sibling progress.

The pinned native Go1.27.2 reference runs modes0-5 and9 in separate processes.
Native main does not implement LSF's accepted-work drain, so late-root,
blocked-work and cancellation cases retain their separate signed assertions.
Reference parity alone is not guest compatibility.

```bash
python3 tools/qualify_go_activation.py --runtime-profile go-component-activation-v5 \
  --fixture synchronization --output /tmp/go-sync
python3 tools/qualify_go_activation.py --runtime-profile go-component-activation-v1 \
  --fixture synchronization --output /tmp/go-sync-negative
python3 tools/qualify_go_synchronization.py --source-commit "$(git rev-parse HEAD)" \
  --fixture /tmp/go-sync --no-checkpoints /tmp/go-sync-negative \
  --output /tmp/go-sync-result
```

The dedicated Linux workflow builds only the required component pair and one
Rust signed-integration target, with owned descendant/output/time bounds. Its
33 required invocation observations reject omissions, duplicated/unknown rows,
private fields and substitute libtest outcomes. Compiler receipts retain their
own compiled/not-run status; the separate signed receipt is written only after
all assertions and original owner cleanup pass. Source/component identities are
checked before and after execution.

This candidate has focused source controls; hosted native-reference/component
and signed execution are pending until the exact run reports. It does not
qualify low-level sockets/DNS/TLS, complete allocation/stack/kernel accounting,
all scheduler interleavings, all native Go behavior or full #742 acceptance.
