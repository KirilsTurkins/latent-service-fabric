# Go maintenance worker ownership

The opt-in `go-component-activation-v5` profile extends the initializer, timer
and checkpoint profiles with ownership for the pinned Go runtime's internal
maintenance goroutines. Select it explicitly when creating a Go project:

```powershell
python tools/go_capsule.py new C:\work\managed-go --runtime-profile go-component-activation-v5
```

The project still needs the activation WIT import, installed runtime provider,
policy binding and deployment grants described in the
[activation profile](../runtime/go-activation.md). A standard library import
creates no host authority. The default profile and v1–v4 remain unchanged.

Before runtime initialization allocates maintenance workers, the compiler
overlay reserves eight `ManagedIdleWorker` capacity slots in the original
activation ledger. This is reserved capacity, including unused slots; it is
not an assertion that eight workers actually exist. These slots share the
operator's existing task ceiling with application goroutines. A ceiling below
eight refuses startup; application work needs additional capacity. There is
no new ledger, automatic task-limit increase or separate activation budget.

The source-pinned runtime worker list can consume only those pre-admitted
slots, before the original goroutine allocation. Exhaustion traps before
allocation. GC can start a worker during canonical allocation, so assigning a
slot, parking, waking or destroying such a worker performs no new component
import. Reserved capacity remains charged throughout the activation.

The classifier covers the reviewed GC, sweep, scavenge, finalizer, cleanup and
runtime processor-maintenance entry points and their exact compiler wrappers.
Application daemon status, an empty queue, a parked channel or a function name
supplied by an application is not admission evidence. Existing application
finalizer/cleanup and native-thread-affinity restrictions still apply.

Retirement first drains all accepted application work under the original
dispatcher. It then checks every remaining goroutine: only an admitted,
source-pinned maintenance worker in the actual waiting state may remain. A
runnable or unknown worker refuses retirement. The overlay settles the eight
original reservations only after this scan. Every scheduler resume, including
GC's direct injection path, retains a fence against post-retirement worker
execution. Token identities stay in guest memory until Store destruction so
late readiness cannot become unowned work.

This classification does not refund heap, stack or runtime metadata memory.
Those bytes remain in the original bounded Wasm linear memory until physical
Store destruction. A trap or cancellation before orderly retirement leaves
uncertain reservations to original Store cleanup. A fresh invocation gets a
fresh Store and initialization state.

## Qualification boundary

The additive Go workflow compiles an unchanged ordinary-source fixture with
real `runtime.GC`, `runtime.Pinner`, channels, `sync.WaitGroup`, initializer
goroutines and timers. Its native reference runs the three ordinary result
modes in fresh processes. The signed-node gate separately checks repeated
fresh invocations, accepted sibling drain, capacity refusal at seven slots,
panic, application cleanup refusal, unknown parked application work,
cancellation, original deadline and fresh execution after failures. Each
terminal path must pass original ledger finalization and physical backend
idle checks. Earlier Go profiles keep all their existing gates and limits.

Source and selection tests do not establish actual component execution. The
new signed campaign remains pending until its owning workflow passes. This
slice does not close [#736](https://github.com/KirilsTurkins/latent-service-fabric/issues/736)
or [#742](https://github.com/KirilsTurkins/latent-service-fabric/issues/742):
cross-language lifecycle coverage, complete host stack/TLS costs and the full
runtime cost/fairness matrix remain separate acceptance requirements.
