# Java collection across parked continuations

Prepared source for a finite part of #741. No new component or collection has
been qualified yet. The original [six-case dependency/monitor programme](java-dependency-checkpoints.md)
and its failed histories and successful evidence remain unchanged.

The new fixture uses the same captured Commons Lang 3.14.0 initializer. A child
retains primitive/reference arrays, an object, a caught exception and independent
ThreadLocal state while waiting on an ordinary monitor. Root reacquires that
monitor after the wait releases ownership and requests one collection. A newly
allocated orphan must have disappeared through its WeakReference. Child resumes,
then requests a second collection while root is parked in the unchanged dependency
call. Both callers check retained identities, contents, exceptions and ThreadLocal
state after resumption. There are no manual weak clears, collection retries,
allocation-pressure loops, custom executors or larger heap grants.

`System.gc()` alone cannot satisfy this programme. Both weak-clear witnesses must
pass, and the standard collector/getter bodies and both continuation bodies are
retained through a separate byte-exact public-fixture selector: twenty-four fixed
C/header files, including `Capsule@d1` for the anonymous initializer. Limits remain
one MiB per file and eight MiB total. Passive real pinned compiler/classlib controls
check the full collector call chain, actual weak-reference lowering and original/
unrelated negatives; those controls remain separate from runtime evidence.

The JVM-only reference explicitly selects SerialGC with explicit GC enabled,
requires its actual collector identities and at least two observed collections,
and has fixed process deadlines. This selected reference configuration does not
turn the Java specification's best-effort `System.gc()` into a universal guarantee.

The focused owning programme requires four signed calls (GC and fresh state in
each of two tenants), two zero-work grant denials and the maintained per-call
physical idle/provider-zero checks and clean node/zero-contact peer shutdown.
It compiles one unsigned compiler warm-up and one fresh target component using
the existing five native193 products without rebuilding them. The original target
64 MiB linear memory, one-billion fuel, 4 MiB Java heap and activation limits are
unchanged. Only activation and the two clock contracts are granted.

Whole scheduler, memory accounting, timer/executor and socket qualification remain
open. No #741 acceptance criterion is marked complete from this source proposal.
