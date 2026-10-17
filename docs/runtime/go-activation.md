# Go activation goroutines, sleep and compiler checkpoints

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

The SDK checkout creator can prepare that explicit selection, including its
async public export shape and captured runtime WIT, without application edits:

```bash
python3 tools/go_capsule.py new /tmp/my-greeting \
  --runtime-profile go-component-activation-v4
```

This selects the current unqualified v4 candidate; it does not install a
provider or grant. Omitting the flag keeps the ordinary default template's
existing WIT/profile. Review the explicit async public ABI when choosing an
activation profile. Native module resolution inherits the project's exact
runtime profile and records it in the captured graph; an explicitly conflicting
selection fails before the resolver runs. Captured dependencies need no
hand-edited runtime selection or application scheduler.

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

The v1 profile does not implement `time.NewTimer`, `After`, `AfterFunc` or `Ticker`:
their timer heap, rearm and callback ownership require further runtime work.
Those APIs fail explicitly during an active invocation. Cooperative Go
scheduling in v1 does not supply compiler safe-point preemption for CPU-only
loops; the original fuel and epoch/root deadline still contain execution.
Initializer background work, unrestricted native threads, CGo and arbitrary
native/WASI operations are outside this profile. These are remaining #742
requirements, so this profile does not establish the complete Go runtime port.

Select `go-component-activation-v2` to add compiler checkpoints to the same
finite goroutine profile. The maintained Go parser inserts a private runtime
call at function/closure entries and loop backedges in selected application
source and its reachable nonstandard vendored modules. Package discovery uses
the captured build tags and module graph; no package name approval catalogue
selects application code. The authenticated Component Model dispatcher remains
separate compiler infrastructure. Every 1,024 checkpoint calls suspend the
current real goroutine through the canonical async callback, allowing runnable
siblings and the host executor to progress. This path creates no timer, wall
deadline, sleeping worker or application-visible scheduling facade.

Original source bytes remain unchanged. Derived copies retain original
diagnostic line/column positions, source and output digests, and suspension
sites in the build transformation materials. The host parser is built and
tested from captured SDK sources before entering compiler containment; it
parses selected modules as data and executes no application initialization on
the build host. Reachable `//go:nosplit` and `//go:nowritebarrier` functions fail
explicitly rather than invoke an unsafe suspension. Native assembly, CGo and
unsupported runtime operations retain their existing boundaries. This profile
does not add standard timer APIs or initializer goroutine support.

The source candidate `go-component-activation-v3` adds the pinned Go timer heap
beneath `time.NewTimer`, `After`, `AfterFunc`, `NewTicker`, timer/ticker Stop and
Reset, and `context.WithTimeout`. Each timer reserves its original host owner
before allocation. The existing Go heap retains synchronous timer-channel
semantics, recurrence, missed-tick coalescing and callback scheduling; the
dispatcher waits on the corresponding canonical `timer-next` operation. This
creates no host sleeping worker or replacement application timer API.

AfterFunc creates an admitted ordinary goroutine with the exact timer's
continuation. Root return drains accepted callback tasks and future callback
timers; channel timers with no remaining application task are stopped during
result sealing. A weak inventory does not keep otherwise collectable Go timers
alive. Explicit Stop/Reset retains pending physical readiness and its buffer
until the exact canonical subtask returns and is dropped, then resumes its
fence. Root cancellation and deadline errors cannot become elapsed success.
The dispatcher checks actual runnable owned goroutines after every scheduler
idle notification: a callback published after the notification requires a fresh
quiescence round before WAIT or EXIT. Unknown parked work still fails.

The candidate's native reference and signed test cover timer/channel Stop and
Reset, recurrence, callbacks, resetting a running callback with permitted
overlap, context cancellation, plain GC, stopped/retained timer GC, collection,
timer limits, callback panic,
root drain, cancellation and deadline. These commands are qualification gates;
source preparation alone does not establish successful execution. In
particular, the latest timer source still needs a successful complete signed
replay before it is a qualified profile. Initializer background work, standard
networking and the complete #742 acceptance matrix remain unfinished.

The first hosted replay of the fresh-quiescence source passed modes 0 through
6, including callback drain, then trapped with memory out of bounds in the
forced-GC case. This remains a failed acceptance result. A failure-only diagnostic
replays that exact component with three private read-only source overlays in a
separate process namespace, preserving the production files and assertions.
It retains at most 32 parsed Wasm function/index/offset records, closed execution
stages/outcome classes, relative Rust assertion sites and input/recipe hashes.
If guest invocation was reached, a second private component replaces only the
known terminal `runtime.throw` and `runtime.fatal` bodies with distinct traps.
This can distinguish an underlying Go terminal failure from recursive denied
stderr obscuring it. Every normal body/import/authority remains unchanged, the
original component and acceptance failure remain intact, and the private
component/body identities are explicit. Both runs share a ten-minute deadline
and one MiB output bound. Raw native errors/configuration are not exported.
This diagnostic cannot qualify the profile, and the job does not save its
diagnostic compiler target or run acceptance afterward.

```bash
python3 tools/qualify_go_activation.py --output /tmp/go-standard-timers \
  --runtime-profile go-component-activation-v3 --fixture timers
LSF_GUEST_SDK_LANGUAGE=go LSF_GO_TIMER_FIXTURE=/tmp/go-standard-timers \
  cargo --config .cargo/managed-guest.toml test --locked -p latent-wasmtime \
  --test local_service \
  runtime::go::signed_standard_timers_contexts_and_rearm_keep_original_heap_owners \
  -- --ignored --exact --nocapture
```

The checkpoint qualification compiles the same ordinary CPU source both with
v2 and without checkpoints. Real signed execution requires sibling progress
through a tight loop and recursive calls, verifies cancellation and the
original root deadline with no host timer, and bounds the negative control by
finite fuel. The pinned native Go reference runs the same reviewed fixture
in a fresh process per supported mode. It establishes observable parity for
those cases; fuel exhaustion alone is not sibling-progress evidence.

```bash
python3 tools/qualify_go_activation.py --output /tmp/go-checkpoints \
  --runtime-profile go-component-activation-v2 --fixture checkpoints
python3 tools/qualify_go_activation.py --output /tmp/go-no-checkpoints \
  --runtime-profile go-component-activation-v1 --fixture checkpoints
LSF_GUEST_SDK_LANGUAGE=go LSF_GO_CHECKPOINT_FIXTURE=/tmp/go-checkpoints \
  LSF_GO_NO_CHECKPOINT_FIXTURE=/tmp/go-no-checkpoints \
  cargo --config .cargo/managed-guest.toml test --locked -p latent-wasmtime \
  --test local_service \
  runtime::go::signed_compiler_checkpoints_progress_cpu_siblings_and_cancel_original_activation \
  -- --ignored --exact --nocapture
```

The additional source candidate `go-component-activation-v4` moves the original
linked module initialization graph into the first admitted async root, before
its ordinary handler. Go runtime bootstrap and GC enablement remain in their
original startup order. Module variables and `init` functions retain the
linker's exact dependency order and run once per fresh component Store. An
initializer can create an ordinary goroutine, block on a condition/channel or
use a timer after the async dispatcher and original task owner exist. It needs
no application initialization hook or transitive-source edit. Compiler material
records `first-admitted-async-root` initialization for captured modules.

This profile preserves logical component initialization; native main-thread
affinity is unsupported. Reached application `runtime.LockOSThread` or
`UnlockOSThread` fails explicitly. Application finalizers/cleanup and unknown
background work keep the same explicit boundaries as the earlier profiles.
An initializer worker waiting for future work remains accepted work: an hour
ticker does not make that worker managed idle, and root return must not discard
it. The original deadline and cancellation apply during initialization too.

The candidate's source transformation has been checked against the exact pinned
upstream files. It has not yet passed emitted-component or signed-node
qualification. Its maintained gate requires the unchanged fixture's native Go
reference and eight signed activations covering blocking variable initialization,
condition signaling, ordered init functions, an initializer-created ticker
worker, explicit shutdown, pending cancellation, unretired-work deadline,
preallocation task exhaustion, unsupported affinity and fresh state. The earlier
v1, v2 and v3 gates remain required. This candidate does not complete #742's
runtime-cost, approved networking and unchanged published transitive-module
acceptance requirements.

```bash
python3 tools/qualify_go_activation.py --output /tmp/go-owned-initializers \
  --runtime-profile go-component-activation-v4 --fixture initializers
LSF_GUEST_SDK_LANGUAGE=go LSF_GO_INITIALIZER_FIXTURE=/tmp/go-owned-initializers \
  cargo --config .cargo/managed-guest.toml test --locked -p latent-wasmtime \
  --test local_service \
  runtime::go::signed_initializer_goroutines_waits_and_timers_start_inside_original_activation \
  -- --ignored --exact --nocapture
```

The additional published workload captures unchanged RxGo `v2.5.0` and backoff
`v4.0.0` through the normal native MVS, module zip, `h1` verification and reviewed
dependency lock. RxGo's ordinary `Defer` producer and `BackOffRetry` worker call
backoff's `Retry`, whose default timer uses standard `time.NewTimer`, `Reset`
and `Stop`. The application supplies a normal retry policy, without an LSF
executor, dispatcher, timer implementation or shutdown adapter. Both modules
are direct native API requirements; the retained graph also verifies RxGo's
dependency edge to backoff, without relabeling either selection as indirect.
Failed attempts in this fixed workload emit an error and have no external
effect. Its retry policy does not authorize repeating an external operation.

The maintained gate builds the reviewed business source on native Go with the
same captured graph offline, then builds the component inside the existing
network-denied compiler namespace. Component checkpoints are recorded as
derived overlays; the captured published source bytes stay unchanged. Signed
execution must pass nine successful activations covering repeated timer reuse,
retry exhaustion and ordinary context cancellation, then original activation
cancellation, root deadline, preallocation task exhaustion and fresh reuse.
The receipt binds the graph, original runtime source files, compiler inputs,
native reference and component separately. This gate has been added as source;
acquisition, component compilation and signed execution have not yet completed.
It preserves the existing pure-module and all earlier runtime gates.

```bash
python3 tools/qualify_go_runtime_dependencies.py --output /tmp/go-published-runtime
LSF_GUEST_SDK_LANGUAGE=go LSF_GO_PUBLISHED_FIXTURE=/tmp/go-published-runtime \
  cargo --config .cargo/managed-guest.toml test --locked -p latent-wasmtime \
  --test local_service \
  runtime::go::signed_published_retry_workers_and_default_timers_keep_original_activation_owners \
  -- --ignored --exact --nocapture
```

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

The retained 2026-10-16 v3 failure remains a required acceptance failure: mode 9
traps while repeatedly collecting unreachable timers. A separate terminal-only
component mutation identified `runtime.throw` behind the original closed-stdio
memory trap. The bounded follow-up compares only 208 reviewed literal reasons
from hash-checked Go 1.27.2 runtime sources. It authenticates the exact emitted
throw body before reading its incoming string ABI, selects fixed terminal traps,
and checks any candidate in one separate fresh full-literal comparison. Only a
reviewed candidate digest and source locations may be exported; identical trap
classifiers elsewhere still require independent caller evidence. These records
prove neither the baseline cause nor a common cause across bit runs. Unknown or divergent
observations remain inconclusive; no normal function body, import, authority or
acceptance assertion changes. All diagnostic executions share the existing
600-second and 1 MiB output bounds. These observations do not qualify v3.

The fresh confirmation on component `3a8776b49b5fa93be27c5797205088a0e43433e4d4d6a889b2d1c1211486f315`
matched the public `fd_write failed` literal in pinned `runtime/os_wasip1.go`.
This can be a secondary failure while printing an earlier ordinary panic. The
additional failure-only probe leaves `gopanic`, recovery, defers and `preprintpanics`
unchanged and authenticates their emitted bodies plus the entire core data
section. It replaces only the already unrecoverable `fatalpanic` body, alongside
the two existing terminal throw/fatal probes. Checked 64-bit pointers, a fixed
builtin-string type, a single-panic chain and a 256-byte limit precede comparison
with 68 reviewed public string or decimal-format families. Every path traps.
Only a family digest and source locations can leave this probe; numeric values
and guest strings are never exported. A separate fresh full-family match is
required. Application strings can match the same family, so confirmation proves
neither runtime origin nor the cause of the original failed invocation. Decimal
widths bound the diagnostic and establish neither integer-range validity nor
complete runtime-error coverage. The original mode 9 acceptance case and all existing
control modes remain required. Hosted job 116880644301 executed this probe and
reported `unknown-panic-family`; it established no runtime cause or repair.

The numeric-frame observer uses a separate private mount view only on the
Linux GitHub Actions runner. The former user-namespace view stopped at policy
store preparation before guest execution. Creating mounts while retaining the
ordinary host user namespace requires `sudo`; the command then uses `setpriv`
to restore the original runner UID/GID, clear supplementary groups and all
capabilities, and prohibit gaining privileges before Python or Cargo runs.
A bounded preflight checks those credentials, the original UID map and root
ownership, and the unchanged safe system-temporary ancestor rules. Local or
unsupported contexts refuse this diagnostic. Production policy guards and the
original signed fixture remain unchanged. Only three source files are bound
read-only; their original bytes and the original component are checked after
execution. The writable Cargo cache becomes diagnostic-only: the job saves no
cache and runs no subsequent acceptance. The original 600-second/1-MiB bounds
still apply. A configured observer alone supplies no frame or execution proof.
