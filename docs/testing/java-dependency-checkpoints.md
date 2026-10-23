# Java published dependency checkpoints

This focused programme addresses part of #741's compiler scheduling requirement.
It is prepared source, with no new runtime qualification yet.

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
