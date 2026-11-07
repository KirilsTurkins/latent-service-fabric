# Go shared-cell admission and retirement

This finite reference advances #742's original-owner/fresh-tenant requirements
and #736's bounded admission/physical-retirement requirements. It reuses the
unchanged ordinary `managed-idle-conformance` Go source and existing
`go-component-activation-v5` compiler. No application executor, yield, custom
transport or replacement scheduler is added.

Two independently signed tenant publications of the identical Go component use
one actual local activation manager, backend and physical cell. Each tenant has
its own deployment, capability policy and scoped publication selector. The
existing provider registrations are shared without a second provider/executor.
The auxiliary `packages::callee(42)` publication is a synthetic handwritten
wasm-encoder fixture, never invoked by this Go campaign. Its source snapshot
binds `packages.rs`, `component.rs` and the actual callee WIT, separately from
the maintained Go caller/compiler materials.
The application still requires its original 16 Task slots (including eight
managed reservations), four Wait slots and original request budgets.

The reference deliberately selects a narrower node concurrent-admission ceiling
of one for its single cell. The normal test/operator queue-eight/admission-eight
configuration is unchanged. Therefore an original parked activation must keep
its one node reservation, physical cell, Store and Wasmtime instance while a
foreign root receives the exact node/concurrency ResourceExhausted refusal.
The refusal must not queue, start another Store, lend the live cell or retry.
Retryable error metadata remains advice to the caller.

The same manager checks both directions: tenant A cancellation followed by
fresh tenant B, and tenant B's actual ordinary Go panic followed by fresh tenant
A. A foreign tenant's cancellation request must be nonrevealing NotFound and
leave the original ownership intact. Every successful/failing original owner
must physically retire before reuse; the unchanged Go initializer/global and
real GC/Pinner control verifies a fresh activation rather than reused guest
state. The parked barrier can occur during admitted initialization or runtime;
it does not claim a particular guest instruction has already executed.

The one exact signed Rust target requires 12 ordered observations: eight guest
activations, two admission refusals and two foreign-cancellation controls. A
wrapper success, different target, omitted/reordered barrier, success in place
of refusal, foreign identity or private field is rejected. The existing bounded
Go reference runner binds exact source/component/compiler identities before
and after and preserves bounded stdout/stderr on failure. Native reference
modes 0/1/2 remain separate observables, never signed qualification by themselves.

```bash
python3 tools/qualify_go_activation.py --runtime-profile go-component-activation-v5 \
  --fixture managed-idle --output /tmp/go-admission
python3 tools/qualify_go_synchronization.py --campaign admission \
  --source-commit "$(git rev-parse HEAD)" --fixture /tmp/go-admission \
  --output /tmp/go-admission-result
```

The actual [526 run 39364377075](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/39364377075),
job 118437683583, passed all 12 required observations: eight guest executions,
two exact saturation refusals and two foreign-cancellation controls. Libtest
reports one passed, zero failed/ignored and 49 filtered cases. All three
fresh native reference modes returned 42. The bounded artifact 12239228340
and [lossless receipt](../testing/evidence/go-admission-signed-2026-10-20.json)
bind that exact source revision, component/compiler inputs and 103 unchanged
before/after Git source identities. These are source-specific results.

This reference does not establish general scheduler
fairness, every queue/full-cell profile, late native/provider completion after
Store destruction, complete aggregate physical costs or low-level net/DNS/TLS.
It changes no production implementation or global/default quota and does not
complete #742 or #736.

## Original Task16 saturation reference

The opt-in `task-saturation` campaign selects a separate ordinary Go v5
component. It starts seven goroutines, waits for each to acknowledge that it
is live, and keeps those workers owned on a channel. The successful control
releases and joins them. A second invocation reaches the same barrier and
attempts an eighth worker; a third repeats the successful control on a fresh
Store using the same backend and publication. The existing eight prepaid
maintenance reservations and original Task16/Wait4 profile are unchanged.

The signed harness installs the existing node diagnostic sink before its
invocations. It requires exactly one original `RuntimeTaskLimit` observation
for tenant `tenant-a` and the saturation activation, with the configured bound
16 and requested owner count 17. It separately requires a guest trap and
physical user-space retirement before the fresh invocation. The observation
records a real admission refusal; it does not by itself identify the terminal
trap's cause. Each invocation must use one new Store, with live Stores,
component instances, instance reservations and reserved fuel/memory returned
to zero. The native Go control runs only the successful seven-worker path.

The maintained synchronization reference workflow exposes this campaign via
its `task-saturation` input and retains its source, component, compiler record,
signed output and strict receipt. A current-source hosted signed run is still
required. Source-only checks and the native control are not signed evidence.
Even a successful bounded run does not establish aggregate stack/GC/native
costs, the other owner ceilings, kernel final-free or the complete #742 ledger.
