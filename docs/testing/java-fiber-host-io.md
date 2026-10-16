# Java fiber host import qualification

Status: candidate source and compiler-model controls pass. C compilation,
canonical suspension and signed node execution are pending the maintained Linux
gate. This is one slice of [#741](https://github.com/KirilsTurkins/latent-service-fabric/issues/741),
[#736](https://github.com/KirilsTurkins/latent-service-fabric/issues/736) and
[#744](https://github.com/KirilsTurkins/latent-service-fabric/issues/744).

The explicit `teavm-activation-fibers-io-v1` selection uses the existing Java
compiler, the original declared WIT and the owned activation fibers. Normal
`tools/java_capsule.py build --runtime-profile teavm-activation-fibers-io-v1`
selects this candidate; projects must already declare the runtime and monotonic
clock imports. The default compiler path and `teavm-activation-fibers-v1` keep
their original C import conventions. No application source, dependency worker,
host authority or native thread is substituted by this selection.

## Ownership and readiness

Every actually asynchronous WIT import is lowered using the pinned C generator.
Its argument storage, result area and canonical subtask survive the suspended
Java caller. The original Java Wait owner and resource borrows remain charged
until the terminal result is decoded and the actual subtask is detached and
dropped. Immediate completion has no pending subtask to drop. Unknown native
acceptance retains ownership until Store destruction.

One activation-local canonical readiness set feeds the original Java event
queue. A pending call suspends its caller rather than the whole event pump.
With two existing host waits and no Java timer deadline, the pump waits directly
on that set; it does not allocate a third fallback timer. When a Java timer is
also pending, an unrelated ready caller can interrupt the pump's value-only
runtime wait. This uses nonblocking canonical cancellation, retains blocked
cancellation buffers, decodes a real returned result when present and waits for
physical terminal delivery before releasing storage. Resource-bearing runtime
wait signatures are rejected before generation.

## Maintained checks

The existing 55-minute Java workflow adds a separate `fiber-io` compiler fixture
using the first fixture's verified read-only compiler closure, followed by
`runtime::signed_java_host_imports_suspend_only_their_owned_callers`. Every
existing command and admission guard remains. The signed harness keeps its
original 64 MiB memory, one billion fuel and 120-second activation limits and
the existing owner ceilings, including two timers. Each mode runs in three
fresh activations and requires the existing node idle checks:

| Mode | Required observable |
| --- | --- |
| 0 | The root progresses while its child awaits an actual host import; thread-local values stay isolated. |
| 1 | Two native host waits overlap and both complete without a third timer. |
| 2 | A child accepted before root return drains to completion with no application shutdown call. |
| 3 | A child host completion interrupts a sleeping Java root and both drain. |

The private JDK reference interprets only the fixture's bounded runtime wait
using JDK threads. Its three passing iterations establish the fixture's
observables, not canonical execution. Pinned WIT/C ABI generation, compilation
of all SDK Java sources against both selected profiles, and all four existing
locked TeaVM class-model controls pass locally. The actual C compiler and signed
component execution remain separate required hosted observations.

This candidate does not complete the ordinary default HTTP client overlap,
two unchanged published default-worker libraries, native cancellation/race and
late-wake matrix, cross-tenant isolation or paired runtime-cost measurements.
Those requirements remain open. The existing
[Java authoring qualification](java-guest-authoring.md) retains its own frozen
source and binary attribution.
