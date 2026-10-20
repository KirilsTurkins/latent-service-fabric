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
not execute a compiler or guest. Actual native-17 and signed-43 outcomes are
pending the hosted campaign. Even a pass does not complete arbitrary timer
races, aggregate cost/fairness, node stop or low-level kernel/TLS qualification.
Both issues remain open and historical v3 evidence is not relabeled as v5.
