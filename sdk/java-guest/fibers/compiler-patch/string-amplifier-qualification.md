# Reviewed platform intrinsics and bounded progress qualification

This control qualifies a fixed TeaVM C-frontend profile used by Java activation
fibers. It is not a replacement for component compilation, signed worker-library
execution, or completion of issue #741.

## Native metadata and identity operations

The finder authenticates the locked TeaVM archives, transformed declarations and
hierarchy, exact C target, and ordered intrinsic/generator factory profile. A
final factory rechecks the selected emitters and declarations after factory
initialization and before C output. The factory lists are frozen. Additional,
reordered, replaced or late registrations cannot acquire a finite certificate
merely by retaining a method name.

Three exact operations have certificates: `StringAmplifier.amplify(String)`
emits its argument unchanged; `StringResource.getValue()` lowers to the pinned
resource string-field read and unwrap; and the generated
`CLDRHelper.getDefaultLocale$$create()` returns compile-time static metadata.
The last certificate additionally checks the actual metadata generator map,
original target, captured intrinsic owner and pinned default-locale provider.
The string-array overload and arbitrary resource getters/providers are not
covered. A nominal method lacking a Java body is accepted only for the exact
proved resource read; the general unresolved-call refusal remains in place.

Compiler extensions execute inside the compiler JVM, so this is not a sandbox
for arbitrary plugin code, reflection or classloaders. The normal application
JAR selection path independently rejects executable TeaVM service providers,
including selected multi-release entries, with
`java-executable-compiler-provider-requires-isolation`. The neutral discovered
plugin is a test control, not general extension approval.

## Counted-loop ranks

The generic proof supports ascending and descending signed integer unit steps,
with every backedge dominated by the matching guard and update. A strict bound
may vary: the guarded unit update cannot cross the signed overflow boundary.
Inclusive comparisons require a constant bound other than `Integer.MAX_VALUE`
for ascent or `Integer.MIN_VALUE` for descent. An implicit zero-bound comparison
is handled as a signed comparison, not subtraction. Equality guards, stalled
updates, dynamic inclusive bounds, and wrapping inclusive extremes still refuse.
Existing exception-edge, residual-cycle and transitive-callee checks remain.

A field-backed rank is not presumed to be SSA. Its additional proof admits only
one nonvolatile instance `int` field on an invariant receiver, one matching
unit write, an earlier same-field read, and a store that dominates all backedges.
The loop cannot call a method, initialize a class, allocate, enter a monitor,
contain a nested loop or in-loop exception handler, or write another field.
A closed instruction set prevents unmodelled effects from resetting the rank.
Alias writes, skipped stores, reset calls and volatile fields remain refused.
This proves progress only; ordinary exception, bounds and resource enforcement
are not removed.

## Small math-table initialization

`BoundedMathInitialization` changes only the pinned
`java.math.Multiplication.<clinit>` power-table construction. It parses the same
authenticated TeaVM donor bytes that it hashes, compares the transformed
class declaration and the complete initializer/direct replacement programs,
and validates both selected calls before modifying either.

The two `BigInteger.multiply` calls at power indices 19 through 31 are replaced
with the existing iterative `Multiplication.multiplyPAP` operation. Their
positive five/ten factors have one word, below the pinned Karatsuba threshold;
the original implementation already chooses this iterative operation for
these inputs. Ordinary application multiplication is unchanged. No recursion
exemption is introduced, and the replacement's complete reachable closure
still has to pass the progress proof.

`MathInitializationReference` separately checks every value in both original
32-entry tables and the iterative recurrence against the reference JDK's
`BigInteger` arithmetic. That is JVM arithmetic evidence, not guest execution.
The actual frontend control checks the rewritten initializer's generated C,
while a changed initializer must refuse before output.

## Executable controls

`AmplifierSplitLauncher` separates compiler and class-library/platform loaders.
The actual `CTarget` parses bytecode, performs FULL optimization and generates
bounded C output. Each case runs in a fresh JVM. The frontend fixture
initializers are compiler inputs, not executed JVM programmes.

The original controls retain the generated identity assignment, archive and
hierarchy identity checks, target checks, factory ordering/refusal tests,
inclusive-bound tests, and actual service-discovery hooks. Unreviewed factory
controls throw if invoked, ensuring a negative result is not obtained by
executing the factory first.

`WorkerCompilerControl` adds descending SSA and field-rank cases, overflow and
mutation negatives, the exact resource read and default locale metadata,
changed or late-removed metadata providers, and math-initializer transformation.
Every refusal requires zero C files and bytes as well as the expected diagnostic.

## Running and interpreting the result

With the repository-pinned JDK and Python dependencies, run from the repository
root:

```sh
python3 -m pip install --requirement tools/requirements.lock
python3 -B -m unittest tools.tests.test_java_amplifier -v
python3 -B tools/qualify_java_amplifier.py --output /tmp/lsf-java-amplifier
```

The output must be fresh. `--read-only-cache PATH` selects the normal locked
cache layout without bypassing archive verification. The branch-scoped
`java-string-amplifier.yml` workflow runs this owner on the pinned JDK.

Inspect `result.json`, `commands.json` and `commands/logs/`. Each selected case
requires its own complete marker and correct bounded output. Unknown modes,
partial markers, unexpected output and non-ASCII markers refuse. Failures retain
a failed receipt. The source-bound retained-input ZIP includes the worker,
math transformation and arithmetic reference sources. Input identities are
checked again after the cases finish. Both component and guest execution flags
remain false; the arithmetic reference has a separate JVM-only observation.

The `java-worker-compiler.yml` focused workflow uses the **normal promoted
compiler product**, not the old diagnostic SDK, and invokes the unchanged
`worker-libraries` fixture plus the original signed worker-library runtime test.
It retains only checked public products and bounded logs, not keys or compiler
caches. Its result is distinct from the frontend owner. The full Java authoring
workflow remains required to cover later SDK qualification steps.

Supplementary local runs with another JDK remain labelled separately from
pinned hosted results. A frontend pass is never a waiver for failed component
compilation, signed admission, sibling progress, GC roots or worker retirement.
