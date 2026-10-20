# Finite and cancellable managed Task waits

The compiler-owned TaskWait derivation now has a selected finite wait path.
It retains the authenticated WASI CoreLib, ordinary Task scheduling, exact public
Task.Wait argument checks and aggregate fault/cancellation handling. No
application scheduler, SynchronizationContext, HTTP handler or executor is added.

CLOCK, ACTIVATION, WALL and RANDOM must all be explicitly declared before this
mode is selected. The timer queue uses the same clock and entropy facets as the
existing ordinary task programme; declarations do not install providers or grants.
Without these declarations, the original infinite-only assembly and receipt are
byte-identical to the previous derivation. The default no-task path is unchanged.

The new helper checks actual task completion and an immediate zero-time query
before admitting a timer. Otherwise original Task.WhenAny and Task.Delay run
through the existing bounded stackful pump. The private linked cancellation
source is cancelled and disposed in nested finally handlers, including failure;
the caller token and requested task are preserved. A timeout returns false, an
external cancellation throws with the original wait token, and neither marks the
requested task complete. Original public exception and invalid-timeout precedence,
nested-depth32, context/main-task restoration and provider limits remain intact.
Root cancellation and physical pending work are not successful completion.

The [reference observation](evidence/dotnet-finite-task-wait-reference-2026-10-20.json)
records the exact original CoreLib and two real managed derivations. Infinite-only
output and receipts are identical; the old selection fails the new finite control.
Thirteen cases compare ordinary .NET10 Task.Wait with the exact generated helper
IL, retaining all opcodes, branches, locals and finally handlers. Only its private
queue-pump call is mapped to a host awaiter. This checks finite results, exception
and token precedence and cleanup control flow; it does not execute WASI scheduling.
Five authority/receipt controls and sixteen existing TaskWait controls pass.

The separate [owning lane](../../.github/workflows/dotnet-finite-task-waits.yml)
builds one fresh offline NativeAOT greeting with a normally captured outside
library. Fourteen ordinary Task.Wait cases cover the reference cases and the
unchanged infinite join. Root cancellation and deadline each require a fresh
positive native `wait-for` Pending observation, all five physical owners and
provider charges before the terminal, followed by an infinite-join recovery.
All eighteen cases require exact results, known/reaped calls, original fuel and
memory budgets, zero effects, physical/provider retirement and clean shutdown.
The original grant-omission controls run before the guest programme. The native
products are authenticated Wasmtime48.0.7 products; the lane performs no native
host, engine or five-template rebuild.

The initial [owning attempt](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/39503801919/job/118907566115)
failed before ILC: the filesystem validator expected the old nine-helper method
count after the finite port added its tenth helper. Real pinned Cecil derivations
reproduce the old rejection and now accept exactly 44,744 unjoined, 44,753 infinite
and 44,754 finite unchanged methods. The count comes from the rechecked, validated
TaskWait port; original C# rewrites and both filesystem method preimages remain
unchanged. All 67 focused controls pass. The failed archive remains failed and
provides no AOT or signed credit.

The corrected programme is pending. No guest qualification is claimed from the managed
controls. The existing sixteen-case task programme retains its cases, order,
commands and limits; its exact port assertion now recognizes the selected finite
mode, without claiming a new pass for historical receipts. CPU preemption,
logical threads/Monitor.Wait, full queue/stack/GC accounting and background/late
work lifecycle remain separate #746 requirements.
