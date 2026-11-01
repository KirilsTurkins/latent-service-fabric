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
must prove those eleven replacement classes before a component can be accepted.
Actual six-case signed execution remains required; source and synthetic IR controls
alone are insufficient.

`VolatileDefinitionFinder.java` is the unmodified TeaVM 0.15.0 source, SHA-256
`b8f854640f7cedccb4cd0dddc4993b86259fafc52f0b2ca822d1a432561d90b1`.
The additional private derivation is the exact four-line upstream repair from
TeaVM commit `ae0630dd286cf57bcb4ec175696ae8010e42588c`: when a definition inside a
nested protected body remains live in an outer handler, its reference temporary
must be backed up on entry to that outer handler as well as at its inner
definition. Otherwise a parked continuation can resume with an undefined C
reference and publish it into a live heap field. The published HPPC imports are
relocated exactly as for the other pinned sources. These two replacement class
outputs change no Java application bytecode, GC algorithm, capability, resource
limit, or exception policy; the compiler source hash, corrected hash, class
bytes, selected JAR and loaded JAR remain bound in the existing receipts.

The source's changed assignment visitor is an anonymous class, so javac emits
both `VolatileDefinitionFinder.class` and `VolatileDefinitionFinder$1.class`.
Both exact outputs are replacement inputs; accepting only the outer class would
leave the repaired visitor bytecode behind. The finite compiler closure requires
all 13 replacement classes and refuses missing or additional companions.

The structural-copy-cost observation is default-off and qualification-only. Its
fixed public Java/WIT pair must authenticate before preparation, and its JVM
property is set only after the replacement JAR and all thirteen loaded classes
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

### Non-suspendable progress classification

The private finder's final-reachability pass checks progress independently of
whether `Activation.checkpoint` is reachable. It starts from reachable class
initializers and method/class `@Unmanaged` contexts, follows the actual call
graph, and retains the original exact private `Fiber.start()` managed-entry
boundary. The existing checkpoint-call refusals run first and keep their reason
codes. An excluded cycle without a supported finite argument refuses with
`java-checkpoint-nonsuspendable-progress-741`; fuel exhaustion is not its proof.
Managed loops outside these contexts keep the existing checkpoint transformation.

The generic rule uses a reducible CFG, including exceptional edges, and SSA
induction. Every entry supplies a signed `int`; every backedge must supply
exactly `i + 1`; the dominating continuation test is strict signed `i < limit`.
The limit may be an array length or a getter recomputed at the header: the rank
`Integer.MAX_VALUE - (long) i` still decreases on every cycle because no signed
limit can admit a cycle at `Integer.MAX_VALUE`. Header exception paths cannot
bypass that test, and a body backedge must be dominated by its continuation.
The increment on a traversed backedge cannot wrap. Mutable
flag polling, reset/bypassed updates, unsupported exception cycles and unknown
recursive call components do not acquire this argument. No package name is an
approval, and calls/inner cycles require their own argument. After removing only
ranked backedges, a separate acyclicity check rejects residual cycles, including
self-edges not enumerated by the pinned loop finder. Existing C `DelegateTo`
wrappers must have one reachable static sibling with a compatible signature;
that body is analyzed in the same context. The C object/array header aliases
retain their valid-operand precondition and are not arbitrary pointer conversions.
An asynchronous operation or possibly contended monitor is not made bounded
by a loop-free method body. Normal class-initialization edges retain the owned
at-most-once/in-progress protocol, with every initializer checked independently;
a direct IR invoke of `<clinit>` is not accepted as that protocol. Speculative
unused/uncalled links are not executable roots; an actual call from an excluded
context still requires its complete transitive proof. The absent original
`Allocator.<clinit>` is authenticated, not treated as an exemption for an added
or modified initializer.

The separate runtime argument binds 32 exact original TeaVM 0.15 class entries,
their complete field/method declarations, and normalized bodies. Shared symbol
tables make the pinned `ClassIO`/`ProgramIO` representations comparable; their
SHA-256 digests stream without retaining or publishing application IR. A changed
runtime declaration or body cannot fall back to the generic counted rule. The
normal C `DelegateTo` transformation, JCL platform-marker and branch passes,
reference resolution and class-init insertion are reused. Marker declarations
come from the authenticated original hierarchy. Required data-only layout uses,
such as `RuntimeArray`, and their native structure parents must also match;
unused pointer types do not force missing DCE classes into a lean programme.
The certificate is a compositional finite boundary. Its two ordinary helper
constructors (`Object` and `StackTraceElement`) bind exact original classlib
inputs and actual normalized declaration/body comparisons through the pinned
JCL substitution policy. Frame-name metadata and explicit fallback strings
satisfy the stack element constructor's nonnull inputs; an unconstrained
null-check/Throwable call SCC is not substituted for those actual inputs.
Four additional exact classlib donors bind only fourteen C word operations:
unsigned division/remainder/comparison, IEEE predicates and bit reinterpretation.
No other native operation gains a finite argument from its declaring class name.

The current certificate authenticates **42 runtime/donor entries in total**:
32 runtime entries and ten donors. Besides the two constructor and four numeric
donors, exact `ClassInfo`/`ReflectionInfo` inputs bind the selected native metadata
queries to the original layout. The original `Object.getClassInfo` body also
requires its exact method proof. These rules do not approve class initialization,
allocation, or arbitrary reflective callbacks. Exact `TString`/`TSystem` donors
cover the apparent char-array-constructor/arraycopy recursion: the nested copy
uses a non-null source and a freshly allocated equal-length destination at zero
offsets, so it cannot recurse through error-string construction again. Changed
bodies or declarations do not receive this input-specific argument, and other
Java callees still require their ordinary transitive proof.

The finite runtime families have these arguments under the existing owned
C/OWN_GC ABI and valid heap/metadata invariants:

- Heap/free-chunk and relocation walks consume positive aligned spans within
  the admitted arena, or advance through its finite chunk list.
- Card, region, field, array and bulk-copy scans consume a finite count or
  address range. Heap growth initializes only the newly admitted region range;
  it does not create an unbounded resize-retry argument.
- Mark work consumes objects whose mark bit is set before further discovery.
  The finite admitted heap bounds objects/edges and the existing mark queue.
- Weak-reference/direct-buffer walks consume the runtime's acyclic registration
  lists; buffer superclass walks consume the emitted acyclic class metadata.
- Exception and root traversal consume the owned shadow-stack frame chain and
  finite emitted callsite/location/handler metadata.
- Multi-array recursion reduces the compiler-supplied dimension count; each
  array allocation retains the existing finite heap/failure bounds.

These are source-bound runtime invariants, not a claim that arbitrary raw native
writes preserve a heap or that an unknown external body is bounded. The admitted
native interface is unchanged. An unknown body reached from a non-suspendable
context has no inferred finite argument. Existing heap, stack, invocation, fuel,
queue, observer and cleanup limits stay unchanged; the pass does not grant a
larger heap or promise that every finite computation fits a caller's fuel grant.

The pass retains the existing 65,536-method/block and 262,144-edge/variable/work
bounds. Original proof classes have at most 128 KiB per entry in a regular JAR
of at most 64 MiB. The unchanged archive writer still requires exactly the
original three finder classes and thirteen replacement classes, each at most
1 MiB, and preserves every nonreplacement entry. Digest streams and a strict
public-context proxy lambda introduce no source companion class; the actual
javac output must still pass that unchanged closure before acceptance.

#### Responding to a progress refusal

`java-checkpoint-nonsuspendable-progress-741` means the compiler could not prove
finite progress in the excluded call closure. It does not assert that every
rejected programme is mathematically nonterminating: unsupported finite loop or
recursion shapes also refuse. Keep initializer/unmanaged work finite using the
supported strict counted form, or move waiting and potentially suspending work
out of that excluded context into managed execution. A finite outer loop does
not make an unbounded inner loop or callee safe. Do not remove synchronization,
insert a checkpoint inside an unsupported non-suspendable region, or increase
fuel/heap limits to bypass the refusal.

#### Executable qualification and evidence boundary

The existing context control covers checkpoint-absent initializer and unmanaged
polling negatives, counted/managed positives, and the original GC array body
versus altered-body/layout controls. Run `41223241737`, job `124601967665`, at
source `9e7746600ced8c200638eee1c57e013b79f37ebc` passed ten Python source/acquisition
checks and both original/corrected JVM controls. Its retained `result.json`
records `status: passed`, both context markers, and both eight-case real
C-frontend markers; the selected private JAR preserves the other 1,874 entries.
This supersedes the earlier statement that those controls were unexecuted.

The current `CheckpointCompilerControl` expands the real frontend to twenty
cases per mode. Six corrected cases must reach analysis completion: finite array
initialization, managed polling outside excluded contexts, finite unmanaged
counting, nested counted loops, a changing signed bound, and a strict near-maximum
integer bound. Fourteen must refuse with the owned progress diagnostic: direct,
transitive and virtual initializer polling; method/class unmanaged polling;
self/mutual recursion; wrapping or reset induction; exception retries bypassing
the update; an unbounded inner loop; and the three altered-runtime controls.
The original compiler must reach analysis completion for all twenty, exposing
the missing refusal rather than executing any of the fixture initializers.
Independent Python checks bind the complete case inventory to the exact marker.

Use the repository-pinned JDK and Python dependencies from the repository root:

```sh
python3 -m pip install --requirement tools/requirements.lock
python3 -B tools/qualify_java_checkpoint_context.py --output /tmp/lsf-checkpoint-context
```

The output directory must be fresh. Inspect `result.json`, `commands.json`, and
`commands/logs/`; a successful exit without the complete original/corrected
markers is not accepted. The bounded `compiler-inputs.zip` retains the selected
public sources, generated finder and locked JARs for replay. Each observation
keeps its actual source/JDK/JAR identities; an older run does not certify a
changed fixture or compiler.

This exercises real bytecode parsing, JCL/C transformations, dependency analysis
and the owning `CTarget` finder, not just a synthetic call graph. It intentionally
stops before optimization and C generation even though the FULL setting remains
selected. It does not compile or execute a guest, sign/admit a component, or
qualify managed sibling fairness and GC roots at runtime. Fresh signed-component
regressions remain separate work. Historical signed GC and checkpoint receipts
keep their original source identities; this partial AC3 repair does not retag
them or complete issue #741.
