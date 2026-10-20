# Pinned TeaVM coroutine corrections

`CoroutineTransformation.java` is the unmodified Apache-2.0 source from
[TeaVM 0.15.0](https://github.com/konsoletyper/teavm/blob/0.15.0/core/src/main/java/org/teavm/backend/lowlevel/transform/CoroutineTransformation.java),
SHA-256 `5fb6d1c6e33fb4418239ec4c3cb93435b194bf5b3d36e8350836e2830567ba8c`.
Its original copyright and license header are retained.

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
