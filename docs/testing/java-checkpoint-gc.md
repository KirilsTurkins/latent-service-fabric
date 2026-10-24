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
state after resumption. An independent activation-local static array strongly
roots only ten weak observers, with its actual generated static-root registration
required. Each collector reads the parked victim through that registry only
after collection. The two ThreadLocal values have no duplicate strong caller
locals; weak observers and `local.get()` check their identities and values. There are no manual weak clears, collection retries,
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
The original producer compiled one unsigned compiler warm-up and one fresh target
component using the existing five native193 products without rebuilding them. The original target
64 MiB linear memory, one-billion fuel, 4 MiB Java heap and activation limits are
unchanged. Only activation and the two clock contracts are granted.

Whole scheduler, memory accounting, timer/executor and socket qualification remain
open. No #741 acceptance criterion is marked complete from this source proposal.


The first GC producer (`a5c4385`, run `39960502389`) completed the reference and
real compiler controls, component and all twenty-four C captures. Its reader then
rejected TeaVM's actual `TEAVM_FIELD(..., TeaVM_Reference, object) = NULL` spelling;
no signed runtime case ran. That failure stays retained. The corrected reader
continues to require reachable mark/sweep and weak-field clearing.

The retained-only continuation authenticates the original whole 106-member archive,
302 original Git preimages, unchanged compiled inputs and separate current
controller identities. It restores only five missing package files against the
original package-input digests: three WIT files generated from the unchanged
source template, and two resource files extracted from the same pinned Commons
JAR. It runs the unchanged four signed cases and two denials, with zero guest or
native compilations. The retained selection keeps its exact compiled-input/source bridge and refuses
changed inputs; it cannot relabel this historical component as a newer build. Reference/control results retain their original failed-job origin;
only new signed results can establish the component's collection witnesses.


The retained-only attempt (`6b72fccc`, run `39966347038`) passed authentication,
package recovery and both grant denials, then its first GC call trapped after
about five seconds. No signed GC case passed. A failed root check could leave the
accepted child waiting; a child initializer exception could leave Commons'
factory claimed before its result was published, masking the original error.
The next fresh fixture records finite collector/victim/own-root phases and
completes only these failure paths: abort/notify/join for a failed root, or a
recorded child failure followed by normal null publication and child settlement.
The existing child-failure guard rejects that null before any result use or
success. Collection flags, weak-clear witnesses, success strings and budgets
remain unchanged. This is diagnostic error completion, with no underlying GC
runtime fix claimed. The push-owned programme now selects the fresh compiler
job (one maintained unsigned warm-up plus one target; zero native builds).
