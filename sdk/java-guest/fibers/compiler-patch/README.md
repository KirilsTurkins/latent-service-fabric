# Pinned TeaVM coroutine copied-phi correction

`CoroutineTransformation.java` is the unmodified Apache-2.0 source from
[TeaVM 0.15.0](https://github.com/konsoletyper/teavm/blob/0.15.0/core/src/main/java/org/teavm/backend/lowlevel/transform/CoroutineTransformation.java),
SHA-256 `5fb6d1c6e33fb4418239ec4c3cb93435b194bf5b3d36e8350836e2830567ba8c`.
Its original copyright and license header are retained.

The captured Python compiler helper checks that complete preimage before adding
the copied-block ID set and changing one copied-phi predicate. Copied phi inputs
must retain both redirected original-domain predecessors and internal copied
predecessors. The original-block phi filter is unchanged. Removing the latter
inputs can leave an empty used phi and an undefined reference temporary in C.

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
