# Java fiber host import qualification

Status: the maintained Linux programme passed canonical suspension and signed
node execution at source `89c7625531d16f1a3dd33408e69a4e705df1d347`.
The finite proof below supplements the dated failures and compiler-model controls;
it does not complete the Java runtime profile. This is one slice of [#741](https://github.com/KirilsTurkins/latent-service-fabric/issues/741),
[#736](https://github.com/KirilsTurkins/latent-service-fabric/issues/736) and
[#744](https://github.com/KirilsTurkins/latent-service-fabric/issues/744).

The [first hosted attempt](evidence/java-fiber-host-io-failed-2026-10-16.json)
stopped in the existing UTF-8 source control before component compilation. Its
minimal TeaVM `Address` declaration now includes `toInt()`, matching the real
dependency. All 9,466 original UTF-8 cases pass on JDK 25.0.3. This dated failure
retains its original scope; the later signed execution is recorded below.

The [subsequent I/O component](evidence/java-fiber-io-validation-failed-2026-10-16.json)
was retained from the worker-library PR's shared I/O prerequisite. Its actual
bytes reproduce the default validator's rejection of async `subtask.cancel` and
pass with only `cm-more-async-builtins` added. The explicit I/O compiler profile
now selects that feature; other profiles retain their original validation call.
The activation engine already selects the corresponding builtin setting. No
runtime capability or engine setting is changed by this compiler correction.

The explicit `teavm-activation-fibers-io-v1` selection uses the existing Java
compiler, the original declared WIT and the owned activation fibers. Normal
`tools/java_capsule.py build --runtime-profile teavm-activation-fibers-io-v1`
selects this candidate; projects must already declare the runtime and monotonic
clock imports. The default compiler path and `teavm-activation-fibers-v1` keep
their original C import conventions. No application source, dependency worker,
host authority or native thread is substituted by this selection.

## Ownership and readiness

Every actually asynchronous WIT import is lowered using the pinned C generator.
Generated callers admit their original Wait owner before marshalling arguments,
so a declared quota refusal cannot consume an owned resource or acquire a borrow.
The reservation is released if marshalling fails before native entry. Once native
entry is attempted, only actual terminal completion permits release; uncertain
acceptance keeps the reservation through Store destruction. The generated-Java
admission control executes the real SDK bridge, resource wrapper and writer on
the JDK with a controlled registry boundary. It checks owned and borrowed quota
refusal, pre-entry Wait refund and uncertain-entry retention; it is a source control,
separate from component execution.
This fixes admission ordering. The existing writer still consumes each owned
handle while serializing it; a later argument-encoding failure does not restore
an earlier consumed handle. The malformed-string control proves the Wait refund,
not a transaction across owned arguments.

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
locked TeaVM class-model controls pass locally. Those controls and the retained
hosted C build remain distinct from actual signed component execution.

The later [full Java job passed](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/38967018900/job/117195890632),
testing merge `6890f9d1b51fe08dcd2dd3398c50868cfeca452b` at the source stated
above. The I/O component
`sha256:c1ca2591a4858cd95d65b0c805bac3a0422e39626d1d4553b671e6bf82f63068`
passed all four modes in three fresh activations each, with the unchanged limits
and idle checks above. The companion activation-fiber programme passed its
twelve mode/iteration pairs, and all twelve SDK runtime tests passed with no
ignores. Retained receipts verify unchanged before/after inputs, 350
authoring source paths, all 356 selected Git paths and twenty recipe inputs per
programme. These observations bind to those exact sources and components;
future changes to selected compiler, runtime or fixture inputs require their own
qualification. They do not establish release installation or publication.

This candidate does not complete the ordinary default HTTP client overlap,
two unchanged published default-worker libraries, native cancellation/race and
late-wake matrix, cross-tenant isolation or paired runtime-cost measurements.
Those requirements remain open. The separate
[published worker-library candidate](java-published-worker-libraries.md)
records the separate two-library gate. The existing
[Java authoring qualification](java-guest-authoring.md) retains its own frozen
source and binary attribution.
