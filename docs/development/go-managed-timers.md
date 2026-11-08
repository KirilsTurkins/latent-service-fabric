# Standard Go timers under managed-v5 ownership

This source-specific campaign advances the ordinary timer, GC and original-owner
requirements of #742 and the timer/drain boundaries of #736. The unchanged
`timers-conformance/main.go` runs through the maintained compiler's existing
`go-component-activation-v5` profile. It uses the original 16 Task slots (eight
managed reservations), four Wait slots and two Timer slots; request CPU, memory,
deadline, peer and cell policies are unchanged. No application yield/executor,
new runtime profile, quota increase or early ownership refund is introduced.

The earlier activation-v3 timer campaign remains intact. Its full result,
elapsed-time, telemetry and physical-idle oracle is also applied to v5, where
managed GC workers and application timers must coexist. The fixture selection
is closed over the existing source/profile pairs: a v5 timer capture must use
the actual timer source, not the separate managed-idle source. Compilation now
retains its 17 fresh native Go reference modes, excluding mode 4 whose accepted
AfterFunc must drain past the component's root result rather than process exit.

The exact signed target requires 43 ordered outcomes: 18 ordinary timer modes
twice, Timer-capacity refusal and fresh success, callback panic and fresh
success, original-root cancellation, its original 100 ms deadline, and final
fresh success. Those modes preserve Stop/Reset/rearm, zero-delay and overlapping
callbacks, monotonic/context deadlines, GC and Pinner checks. The accepted
AfterFunc case must still take at least 20 ms and every invocation must reach
physical idle. Each 18-case batch consumes and reconciles its own telemetry
within the unchanged 32-entry observation bound.

```bash
python3 tools/qualify_go_activation.py --runtime-profile go-component-activation-v5 \
  --fixture timers --output /tmp/go-managed-timers
python3 tools/qualify_go_synchronization.py --campaign managed-timers \
  --source-commit "$(git rev-parse HEAD)" --fixture /tmp/go-managed-timers \
  --output /tmp/go-managed-timers-result
```

The dedicated `Actual Go synchronization reference` workflow selects this one
campaign on its feature branch or explicit `managed-timers` input. The normal
Go workflow also requires it, retaining the original v3 and every other gate.
The bounded runner authenticates unchanged Go/component/compiler/source inputs
before and after; it rejects a wrapper-only success, wrong/ignored target,
missing/reordered observations, changed outcomes and unknown/private fields.
Compiler and signed failure stdout/stderr remain bounded and retained.

Local controls verify source selection and strict evidence parsing; they do
not themselves qualify a guest. An additional host-only Go control executes
the actual collected-timer sweep and idle drain with a deliberately parked weak
conversion. It checks stop and reset of the old timer, slot reuse and growth,
and repeated scanning when a completed fence permits an earlier slot to be
reused. The drain traps after 8,193 passes if the inventory cannot settle; its
work remains charged to the original activation budget. The control simulates
the GC scheduling boundary and host retirement; it is not a signed guest, a
real GC pause, or physical-limit qualification. The actual
[37cf run 39369515637](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/39369515637),
job 118453969321, passed all 43 signed outcomes and all 17 fresh native modes.
Libtest reports one passed, zero failed/ignored and 50 filtered cases (11.72 s).
Artifact 12241945138 and the [lossless receipt](../testing/evidence/go-managed-timers-signed-2026-10-20.json)
bind all 104 unchanged selected Git sources and compiler/component identities
before/after. Every native mode returned 42 with empty stderr. All 36 positive
component consumptions are retained; the two accepted AfterFunc controls took
30,412 and 31,583 microseconds, preserving the original 20 ms minimum.

The later additive queue/timer test-runner/YAML/catalogue composition retains
the exact timer and queue oracle bodies and all existing commands. The full
production native source, Go SDK/compiler and compiler material inputs remain
unchanged. Its strict catalogue has 52 cases; the historical actual run keeps
its original 50 filtered count and tested revision. No repeat guest execution
is claimed for the later test/documentation composition. Even a pass does not complete arbitrary timer
races, aggregate cost/fairness, node stop or low-level kernel/TLS qualification.
Both issues remain open and historical v3 evidence is not relabeled as v5.

## Garbage collection during an outstanding timer wait

The separate timer-overlap owner retains the original Reset/Reset and
Reset/Stop cells and adds one forced-collection version of each. In those cells,
the second worker first stops its marker timer; the host witness accepts that
marker only after the first worker has parked while the original provider wait
is pending. The worker calls `runtime.GC`, checks that `NumGC` changed, then
starts and stops a ticker with a distinctive period. After that Stop returns,
the worker signals the root and parks on a release channel. The root creates a
second distinctive ticker before it releases the worker. The host tracks park
and wake transitions and accepts the root marker only while the second worker
is already parked. It ignores earlier parks, including a possible GC-marker
fence, and accepts a later park only after that observed handshake. The host
retains the original provider wait until then and requires physical wait
retirement. A passing signed cell establishes a collection between those
observed events.
The native reference cells only compare ordinary Go return behavior; the
host witness establishes the guest ordering. A fresh activation follows the
four selected cells. Task16, Wait4, Timer2 and the activation budgets stay
unchanged. The existing 43-case timer campaign remains a separate owner.

This source specifies the new qualification; it is not a signed result by
itself. It does not prove every possible GC/timer interleaving, actual process
RSS, trap quarantine, or the entire #742 timer and physical-cost requirements.

Timer installation allocates replacement inventory separately from its
non-suspending publication step, which rechecks the current slots after any GC
pause. A host-only control forces allocation to pause while other admitted
timers install, grow the inventory or release a slot. It checks that all live
tokens retain distinct slots and callback counts. A separate million-attempt
host GC stress did not reproduce the original lost-slot interleaving. Neither
control is a signed-guest or actual-GC-park result for the revised source.

Timer readiness publishes its wait record before starting `timer-next` and
rechecks the selected timer after allocation. A stopped or superseded timer
therefore cannot create an untracked host subtask. All fence callers observe
one durable completion channel, which is closed only after an actual pending
subtask is dropped or the unstarted wait is abandoned. Host-only controls
exercise the allocation and completion interleavings using simulated host
readiness; signed guest execution of this revised path remains unqualified.
