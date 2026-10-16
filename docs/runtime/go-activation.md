# Go activation goroutines and sleep

`go-component-activation-v1` is an explicit finite compiler profile beneath
ordinary Go `go`, channels, `select`, `sync.Mutex`, `sync.WaitGroup` and
`time.Sleep`. It uses the pinned Go 1.27.2 compiler and componentize-go 0.4.3
from the [Go SDK](../../sdk/go-guest/toolchain.lock.json), with authenticated
runtime and dispatcher source overlays. Application source imports no LSF task
facade. The existing `go-component-async-v1` default remains separately selected.

Set `runtimeProfile` to `go-component-activation-v1` in `capsule-project.json`.
For captured dependencies, select that same profile in the captured native
module selection; disagreement is rejected. The selected WIT world must
explicitly import `latent:runtime/activation@0.1.0`, with its captured package
under `wit/deps`, and expose async functions. The compiler rejects missing
runtime imports and synchronous export shapes. The node operator must install
and grant the [activation runtime](activation-runtime.md), clocks and entropy
for the exact publication. Selecting a profile supplies no authority.

Before allocating a new application goroutine or its stack, `newproc1`
reserves a task on the original host ledger. A live parent supplies its exact
generation token for accepted continuations during drain. Channel and sync
parking/waking update that same task; blocked work remains charged. Only actual
`gdestroy` settlement releases its logical owner. Recycled stacks remain in the
original Store's charged linear memory until physical Store retirement.

The generated async entry closes admission after the ordinary handler returns,
waits for every accepted sibling to exit, then seals the result. A sibling panic,
unknown parked work, denied admission or unconfirmed settlement cannot produce
success. A finite list of pinned runtime GC housekeeping entry points is
separate from application tasks. Pre-entry initializer goroutines are rejected.
Application finalizer and cleanup registration is rejected, including during
initialization. Only the exact pinned runtime Pinner leak-check and `os.file`
close finalizers are permitted as housekeeping; neither calls application code.
The closed adapter supplies no real file descriptor authority. Sleeping work
is never classified harmless by name prefix or daemon status.

`time.Sleep` suspends its real Go goroutine through the canonical async waitable
set and the original host `wait-for` continuation. Siblings progress while the
host owns readiness. Cancellation, a narrower policy deadline and the root
deadline do not report requested elapsed success. There is no guest busy wait,
WASI polling, host sleeping worker, detached timer or new deadline.

This slice does not implement `time.NewTimer`, `After`, `AfterFunc` or `Ticker`:
their timer heap, rearm and callback ownership require further runtime work.
Those APIs fail explicitly during an active invocation. Cooperative Go
scheduling also does not supply compiler safe-point preemption for CPU-only
loops; the original fuel and epoch/root deadline still contain execution.
Initializer background work, unrestricted native threads, CGo and arbitrary
native/WASI operations are outside this profile. These are remaining #742
requirements, so this profile does not establish the complete Go runtime port.

Run the maintained emitted-component preparation with the pinned tools on PATH:

```bash
python3 tools/qualify_go_activation.py --output /tmp/go-activation
LSF_GUEST_SDK_LANGUAGE=go LSF_GO_ACTIVATION_FIXTURE=/tmp/go-activation \
  cargo --config .cargo/managed-guest.toml test --locked -p latent-wasmtime \
  --test local_service \
  runtime::go::signed_standard_goroutines_sleep_and_drain_use_original_activation_owners \
  -- --ignored --exact --nocapture
```

Use a fresh output directory. Compilation retains component/source/tool and
overlay identities and explicitly reports `signedExecution: not-run`. The
separate signed test checks ordinary channels/sync/sleep, result drain, nested
accepted continuations, task exhaustion, sibling failure, unsupported timers,
unknown parked work, cancellation, root deadline and fresh reuse. It uses the
normal package admission, grant, execution-cell and physical cleanup owners.
The Go workflow retains both successful and failed artifacts. A prepared command
or compiler receipt alone is not execution or complete-ticket qualification.
