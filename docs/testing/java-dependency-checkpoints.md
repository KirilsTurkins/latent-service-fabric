# Java published dependency checkpoints

This focused programme addresses part of #741's compiler scheduling requirement.
[Run 39951552847](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/39951552847/job/120406973356)
passed the six signed cases on source `2ea9ef407f64634bd2b4b92fac2fbc7e84b5e50f`.
The [verified receipt](evidence/java-dependency-checkpoints-signed-2026-10-23.json)
binds the source, compiler controls, generated C, component and runtime observations.

The fixture calls unchanged Commons Lang 3.14.0 `AtomicSafeInitializer.get()`.
The original Maven archive digest is
`7b96bf3ee68949abb5bc465559ac270e0551596fa34523fddf890ec418dde13c`.
Its [published implementation](https://github.com/apache/commons-lang/blob/rel/commons-lang-3.14.0/src/main/java/org/apache/commons/lang3/concurrent/AtomicSafeInitializer.java)
contains an atomic-reference spin loop. A child wins initialization and waits
until the root signals that it is about to call `get()`. The root then enters
that dependency method immediately, with no application yield or wait in between.
The cooperative guest can finish only by scheduling the child from a dependency
checkpoint. The JAR and application source receive no injected executor or yield.

The second mode holds a reentrant monitor across that call and checks its
ownership before release. Both modes check independent logical ThreadLocal
values, one initialization, a retained array and original caught exception,
start/join behavior, and fresh static state. These are retained-object
observations; no actual garbage collection is claimed.

The real maintained compiler plugin is also executed against the selected JAR's
passively loaded TeaVM IR. It must add one checkpoint per real loop header while
retaining every original instruction. Unselected classes, class initializers and
`@Unmanaged` methods retain their exclusions. This model control initializes no
application class and remains separate from reference-JDK and signed execution.

The maintained compiler additionally checks the final resolved caller closure of
the SDK's `Activation.checkpoint` before async classification and coroutine
transformation. A direct or transitive call from `<clinit>`, a method marked
`@Unmanaged`, or a class marked `@Unmanaged` is refused with a fixed #741
diagnostic. Managed shared helpers keep their checkpoints. The exact pinned
private `Fiber.start()V` is the managed-entry boundary: it installs the current
Fiber before running its callback, so its callers are outside that new context.
The boundary requires its resolved body to match the original Fiber body parsed
directly from the same authenticated compiler JAR, with the same method flags
and the pinned production `PreOptimizingClassHolderSource` pass, bounded
instruction operands, phi inputs and normal control flow. The pinned body's
operandless NOPs retain their exact type, position and count. Empty,
altered, exceptional or unknown instruction bodies cannot establish that proof.
Other methods and overloads receive no such exemption. The independent walk
allows at most 65,536 methods and 262,144 combined call-site/caller-edge visits;
incomplete metadata or an exceeded bound refuses compilation. Direct loops in
`@Unmanaged` classes are also excluded from instrumentation.

The separate `Java checkpoint context compiler control` workflow runs original
and corrected TeaVM classes on the JVM with the existing fifteen locked model JARs, including the core compiler's declared
runtime dependencies for the real dependency analyzer.
Its controls include real completion-time dependency analysis adding a late
unsafe path, pinned call-graph/IR cases and managed-entry positives. It compiles
no guest/native component and supplies no runtime or whole-criterion proof.
The existing compatibility report maps an observed unsupported-context refusal
to `missing-runtime-port`; bounded or unresolved analysis remains
`unresolved-behavior`. All findings retain source/compiler binding and no authority.

The programme uses the maintained Maven capture/review and offline Java build.
When no verified compiler cache is supplied, its existing unsigned greeting
warm-up compiles first: two components are compiled in total, only one of which
is the new signed target. Five existing native products retain their separate
`b422af24d86344ac7abb8b8fa56c3782aab63915` origin and 193-control producer evidence;
no native host is rebuilt and no historical guest is relabelled.

Six signed calls reuse one node across two tenants, following two pre-entry
runtime-grant denials. The original 64 MiB memory, one-billion fuel, 4 MiB Java
heap and Java activation owner limits remain unchanged. Only monotonic clock,
wall clock and activation runtime authority are granted. Every actual call must
have its exact result/revision, known outcome, reaped caller and physical idle
observations; the node and zero-contact observation peer must be clean/reaped.

Full scheduler coverage, collected GC-root proof, active/parked/native memory
costs, complete accounting, non-suspendable regions beyond these exclusions,
socket integration and whole #741 completion remain open.


The first three focused campaigns preserved a real monitor failure. The unchanged
dependency loop returned 42, but the monitor case trapped. The third campaign
retained eight exact adapted C/header pairs and reproduced the byte-identical
second component. It showed a missing child monitor suspension boundary. The
follow-up corrects the pinned compiler's premature empty-set monitor discovery,
requires real original/fixed IR controls and all eleven actual loaded replacement
classes, and checks the emitted child guard before the same six signed cases.
No failed campaign is relabelled as qualified, and no case or original limit is waived.

The successful follow-up ran both original and corrected monitor IR controls,
verified eleven loaded replacement classes and 1,866 unchanged compiler JAR
entries, and retained the real child monitor guard and resume state. All six
signed dependency, monitor and fresh-state calls passed across both tenants.
Both missing-runtime-grant calls were refused with zero guest fuel and memory.
Each successful call had eighteen zero active provider counters and physical
idle observations; deletion, clean node shutdown and the zero-contact peer
completed. The OS observations are finite scans; RSS is not a retirement proof.
The original limits, fixture assertions and three failed campaigns remain intact.
