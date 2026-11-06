# StringAmplifier and inclusive progress qualification

This focused control owns the finite `StringAmplifier.amplify(String): String`
certificate and its interaction with the selected TeaVM C frontend. It is not a
replacement for signed worker-library execution or completion of issue #741.

## Supported proof boundary

The production finder authenticates the locked TeaVM platform archive, the
exact transformed declaration and owner, and the selected C target. It accepts
only the reviewed ordered intrinsic/generator factory profile. A final factory
checks the actual initialized emitters before class output. The certified
operation emits its argument unchanged; `amplifyArray` is not certified.
Additional, reordered, replaced or late factory registrations cannot acquire
this finite argument merely by retaining the original method name.

The generic loop rank also permits `i <= constant` when the constant is below
`Integer.MAX_VALUE`. The existing SSA `+1` update, dominance, exceptional-edge,
residual-cycle and transitive-callee requirements remain. An inclusive dynamic
bound is not supported, even when a fixture assigns that bound a small value.
`i <= Integer.MAX_VALUE` remains refused because its increment can wrap.

These checks constrain the reviewed compiler profile. Compiler extensions run
inside the compiler JVM; this control does not establish containment of arbitrary
plugin code, reflective mutation, custom classloaders or every possible plugin
interaction. A no-op extension that leaves the selected profile unchanged is a
positive discovery control, not general extension approval.

## Executable controls

`AmplifierSplitLauncher` separates the compiler loader from the class-library,
platform and fixture loader. The actual `CTarget` parses bytecode, performs
FULL optimization and generates bounded C output. Each case runs in a fresh JVM;
the Java fixture initializers are compiler inputs, not executed JVM programmes.

The original controls retain their identity-assignment check and refusals for
changed archives, declarations, hierarchy, target, factory order and factory
replacement. Late intrinsic and generator registration must both be refused.
The changed-archive case mutates class metadata in the emitter entry while
preserving a valid, equal-size ZIP; it demonstrates archive-identity checking,
not a complete catalogue of executable emitter mutations.

Additional cases compile an initializer that combines the identity intrinsic
with `i <= 18`, and one using a finite inclusive bound near `Integer.MAX_VALUE`.
Separate overflow and dynamic-inclusive fixtures must refuse before C output.

`AmplifierPluginControl` is a test-only `TeaVMPlugin` discovered through a
`META-INF/services` descriptor in a separate copy of the control model. No
provider descriptor is added to the SDK or the baseline control model. Cases
exercise a neutral plugin, intrinsic/generator registration during installation
and dependency completion, and a declaration transformer. Each extension case
asserts actual discovery; completion and transformation cases assert their
hooks ran. Unreviewed factories throw if invoked, so a refusal cannot pass by
executing those factories first. All negative controls require zero output
files and bytes, in addition to the expected progress diagnostic.

## Running and interpreting the result

From the repository root, with its pinned JDK and Python dependencies:

```sh
python3 -m pip install --requirement tools/requirements.lock
python3 -B -m unittest tools.tests.test_java_amplifier -v
python3 -B tools/qualify_java_amplifier.py --output /tmp/lsf-java-amplifier
```

The output directory must not already exist. `--read-only-cache PATH` may select
an existing cache in the normal locked dependency layout; archive identities
remain checked. The branch's `java-string-amplifier.yml` workflow runs the same
commands with the repository-pinned JDK.

Inspect `result.json`, `commands.json` and `commands/logs/`. A passed result
requires each selected case's own complete marker and its expected bounded
output. Unknown modes, partial markers, unexpected output and non-ASCII markers
are refused. Preparation or execution failure writes a failed receipt, not a
passed or indefinitely started result. The source-bound retained-input ZIP
includes the extension fixture; the receipt records the generated provider
identity. Input identities are checked again after the cases finish.

Both `componentExecutionPerformed` and `guestExecutionPerformed` remain false.
A successful frontend result does not mean the generated C was compiled or
executed, or that Java sibling fairness, GC roots, signed admission or worker
retirement passed. Supplementary local runs with a different JDK must remain
labelled separately from the pinned hosted result. The unchanged published
worker-library fixture has its own compiler and signed-execution obligations;
its `java-checkpoint-unresolved-741` failure must not be waived by this control.
