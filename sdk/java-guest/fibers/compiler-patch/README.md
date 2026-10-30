# Pinned TeaVM coroutine corrections

`CoroutineTransformation.java` is the unmodified Apache-2.0 source from
[TeaVM 0.15.0](https://github.com/konsoletyper/teavm/blob/0.15.0/core/src/main/java/org/teavm/backend/lowlevel/transform/CoroutineTransformation.java),
SHA-256 `5fb6d1c6e33fb4418239ec4c3cb93435b194bf5b3d36e8350836e2830567ba8c`.
Its original copyright and license header are retained.

The private derivation also supplies a complete structural copy-cost input to
the existing irreducible-graph splitter. Its positive initial weight counts the
block, instructions, PHIs and incoming records, ordered handlers and exception
binding. It is an IR-copy heuristic, not a measured Wasm byte or runtime cost.
The graph/splitting algorithm, FULL/O2 and EH/SjLj semantics are unchanged.

Private inherited weights track each actual original/copy node. Every proposed
copy's positive weight is checked against the global `int` total before creating
any block; the unchanged splitter's domain/collapse/subgraph accumulations are
subsets of that bounded total. Arithmetic overflow refuses compilation instead
of wrapping or saturating. This does not raise any compiler or guest limit.

The separate fixed `copy-cost` JVM IR control runs the actual splitter
on two metadata-heavy domain variants, checks PHI/handler preservation and real
copy choices, preserves a reducible graph exactly, and exercises refusal before
mutation on a forced accumulator overflow. It emits its own closed three-case
record and cannot receive implicit credit from an old run. The old
`original`/`corrected` command lines, JSON schemas and all prior assertions remain. These new controls are
source-only until their hosted JVM execution; they do not prove that the actual
public `pools` method changes or fits the unchanged parser limit. A later bounded
qualification must stop before Clang if the hook is not reached or generated C
does not improve, without tuning coefficients or changing Java/WIT/FULL/O2.

The captured Python compiler helper checks that complete preimage before adding
the copied-block ID set and changing one copied-phi predicate. Its three HPPC
imports receive the exact `com.carrotsearch.hppc` to `org.teavm.hppc` relocation
used by the pinned release's `settings.gradle.kts`; the already pinned relocated
JAR's three required classes are checked before compilation. Copied phi inputs
must retain both redirected original-domain predecessors and internal copied
predecessors. The original-block phi filter is unchanged. Removing the latter
inputs can leave an empty used phi and an undefined reference temporary in C.

The entry-block correction carries the original block index into liveness
queries. TeaVM analyzes the original graph before its split prologue moves block
zero into a continuation appended at the original block count. Querying that
new index in the original liveness table fails out of bounds; it must query
original block zero. The other original blocks retain their indices. The fixed
IR control separately requires that original failure and a corrected single
async call with the integer live across it retained in the saved state.

The pinned JDK compiles only this class, its two generated companion classes,
and the fixed IR control against the already checksummed compiler JAR closure.
The original cache is immutable. A private core JAR replaces exactly those three
class entries; every other entry is byte-identical. The control uses real TeaVM
Program/Phi objects and an irreducible loop to require the original defect and
the corrected incoming values in separate JVMs. The real C compiler classloader
must load that owned JAR, with its digest bound into the build observation.

This is a compiler correction, not a C cast, erased loop, change of optimization
level or scheduler allowance. Source-only controls do not establish successful
component compilation or signed HTTP lifecycle behavior; those require the
focused hosted campaign.

The already-required original `classes` task records its resolved buildscript
classpath. Each ordered artifact must match the pinned compiler inventory;
only its single core JAR is replaced, with every transitive artifact retained.
This avoids relying on file-dependency ordering alongside the original module.
The original in-process compiler mode is checked, and `generateC` still refuses
unless its actual `CTarget` classloader selects the exact owned replacement.
A refusal retains only a closed loader category and bounded source digest.

Run `39367488958`, job `118447530336`, established both real JVM IR controls,
then refused at that load fence. It did not compile a component or execute the
signed lifecycle programme. The corrected Gradle selection needs its own
hosted result; the earlier refusal remains retained.

Run `39461289033`, job `118761117056`, subsequently established the exact owned
compiler JAR load but failed in `LivenessAnalyzer.liveOut` while processing the
appended entry continuation. Its bounded public compiler stack identifies this
separate defect; no guest ran. The entry-liveness correction still requires its
real original/corrected IR controls and fresh component execution in hosted CI.

Run `39467113742`, job `118781269087`, then passed both real original/corrected
JVM controls, including the entry-liveness regression, and generated C with the
exact private JAR loaded (`2e36303865fe91c639bf42b992c12d149d329ed1f64f71291b42d5404bf04105`).
Its next clang stage failed on an integer GC-root argument in `TimeZone.c`.
That separate generated-code failure does not invalidate the observed IR result;
it still means no component or signed Java invocation was produced.


The monitor continuation correction also pins the unmodified `AsyncMethodFinder.java`
from TeaVM 0.15.0, SHA-256
`510b04fa6db5c0a47dc9656643bb3b1af0a104ed66cfb32786b88f93bbb4740d`.
Its original `find()` computes monitor support before discovering annotation roots;
the original helper scans the still-empty async-method set and therefore disables
monitor-only propagation and `MonitorEnterInstruction` splitting. Actual signed
checkpoint run `39948129626` retained generated C showing the child immediately
executing the protected body after a contended asynchronous monitor call, without
a suspension guard or resume state. The six-case programme failed; its ordinary
dependency case succeeded separately.

The private compiler now derives monitor support from the original dependency
analysis's actual reachable `Thread.start()` before root propagation. All other
annotation, monitor, caller and overridden-family discovery remains unchanged.
Only the finder and its two existing companion classes join the exact private JAR
replacement set; every other entry stays byte-identical. The real original/fixed
JVM control uses TeaVM `ClassHolder`, `Program`, `DefaultCallGraph` and coroutine
transformation, with finite explicit reachable inputs. It checks monitor-only and
already asynchronous callers, suspension guards, caller/family propagation, the
no-`Thread.start` negative and an unrelated method. It does not qualify arbitrary
class-initializer or unmanaged monitor suspension. The actual compiler classloader
must prove all eleven replacement classes before a component can be accepted.
Actual six-case signed execution remains required; source and synthetic IR controls
alone are insufficient.


The structural-copy-cost observation is default-off and qualification-only. Its
fixed public Java/WIT pair must authenticate before preparation, and its JVM
property is set only after the replacement JAR and all eleven loaded classes
pass the existing identity fence. It adds no replacement companion class.
Production weights do not depend on method names. For the observed public
`pools` method, one copy of the actual pre-normalization Program runs the real
old-weight splitter, while the original Program runs the complete-weight path.
Only bounded structural counts and ordered-decision SHA-256 values leave that
hook. These are compiler observations, not runtime cost measurements.

The private qualification mixin checks the adapted C shape before Clang. Missing,
ambiguous, unchanged or non-improving observations refuse. A strictly improved
candidate reaches the same bounded normal parent Clang command; the gate record
is only a pre-Clang decision, not component acceptance. It selects no compiler
SDK or alternate application. Existing FULL/O2, native EH/SjLj, 64KiB stack, 64MiB
maximum memory and the 7654321-byte function parser limit remain unchanged.
The new JVM cost controls and actual public observation are still unexecuted.
