# Non-suspendable progress: fresh runtime qualification

PR #1588 adds a final-reachability refusal for unsupported progress in class
initializers and unmanaged contexts. The JVM controls and a signed component
exercise different boundaries; neither may stand in for the other.

## Owning workflow

`.github/workflows/java-checkpoint-context.yml` retains the original
`compiler-context` job, tool pins, timeout, and branch route. Its
original/corrected controls include twenty real bytecode/JCL/C-frontend cases per
mode. Run `41294005890` passed for source
`ad707b8c02664fff5fa81f4ec6a29617f61f1f19`; this is JVM evidence, not runtime
qualification.

The additional `signed-progress` job runs only on
`feat/java-nonsuspendable-progress-20261031`, after the JVM job succeeds. The old
`feat/java-checkpoint-context-20261023` branch remains JVM-only. A manual dispatch
on any other ref does not select the new job. There is no wildcard branch route,
new production permission, or change to the separate GC owning workflow.

The job invokes the existing `tools/qualify_java_checkpoint_gc.py` programme. It
uses the same pinned JDK, Gradle, WASI SDK and bindgen installation, and retrieves
the five exact native products through `tools/rust_thread_native_products.py`.
Their source, artifact, receipt and 193-control checks remain mandatory. No Cargo
build, diagnostic-node replacement, retained guest component, or read-only
compiler cache is selected by this route. An expired or mismatched native origin
must fail rather than choosing another artifact implicitly.

The existing qualifier performs its ordinary unsigned compiler warm-up and one
fresh target build. It binds the current source, private compiler JAR and loaded
replacement classes, captured dependency bytes, FULL/O2 settings, and original
4 MiB Java heap. Its generated-code checks precede signed admission and the
unchanged two-tenant programme. Limits, authority denials, GC observations and
cleanup assertions are not relaxed to obtain a pass.

## Reading a result

The JVM artifact remains `java-checkpoint-context-<source SHA>`. The new artifact
is `java-nonsuspendable-progress-<source SHA>` and is retained for three days.
Selected source, build and runtime observations are uploaded even on failure;
private keys, credentials and whole node workspaces are not selected.

A green JVM job establishes only its compiler-control verdicts. A fresh runtime
claim additionally requires `java-progress-gc/qualified.json`, matching build
identities and the node's actual signed observations. A `FAILED.json` preserves
the failed stage and command records. Reaching C generation, producing a Wasm
file, or uploading an artifact is not by itself signed-runtime qualification.
Historical signed receipts keep their original component and source identities.

Even a successful focused GC programme does not close every #741 requirement:
independent lifecycle, timer, socket and general preemption coverage remain
subject to their own evidence.

## First fresh-build observation and monitor-control repair

Run `41299505595`, source `d6dfdbe0d2858aa1500739f2d59d840dd2a47fb2`,
passed the pinned JVM context and twenty-case frontend controls. The new job
also passed the workflow/source checks, exact native-product authentication,
reference-JDK GC observables, actual plugin controls and ordinary unsigned
compiler warm-up. It did not produce or execute the target component: production
compiler preparation failed in `java-coroutine-monitor-corrected-control`.

Artifact `13081080937`, SHA-256
`e1be36e45783bfb9b6947ea45535b12a1ca9f2bc7b0c71bb198fe6e4b26ce145`,
retains `AssertionError: unused-method` from the old `MonitorAsyncControl`
dependency mock. The new final-reachability pass legitimately queries method
metadata even when no explicit checkpoint is reachable. The mock previously
asserted that this API would never be called.

The repaired mock accepts only its explicit reachable-method inventory and
returns absent metadata conservatively, so no method can be marked unused to
skip progress classification. The control asserts exact query coverage in the
corrected mode and no queries in the original mode, with and without reachable
`Thread.start`. All existing monitor, suspension-guard, caller/family and
unrelated-method assertions and the exact two-class fixture output remain.
No production proof, refusal, compiler replacement class or resource limit is
changed by this repair.

The fast JVM qualifier now compiles and runs that same production-build control
in both modes, records `monitorControls`, and binds its source into the retained
input archive. This catches the integration regression before guest compilation.
The old failing mock was reproduced locally against the locked TeaVM JARs; the
repaired original/corrected controls passed using OpenJDK 21 and `--release 11`.
That supplementary replay is not a new pinned hosted or signed-runtime result;
the repaired source requires its own fresh run.

## Production classloader regression and isolated-JCL control

Run `41300387755`, source `fcd2eaebc157e9cb65d5041fcbac1e35898d5891`,
passed the pinned JVM job, including both repaired monitor controls and all forty
frontend cases. The fresh target build then passed compiler preparation but
failed in `java-to-c` with `NoClassDefFoundError` for
`org.teavm.classlib.impl.PlatformMarkerSupport`. It did not produce or execute a
signed target component. Runtime artifact `13081380817`, SHA-256
`776fefacd91110f64f158694ca5eec90d56a1f581fd02d88aa87a902665b3bf7`,
preserves this distinct failure.

The earlier frontend fixture put the class library on the compiler's own
classpath. Gradle instead keeps the compiler in a parent loader and supplies the
class library through the explicit application/dependency loader. The finder
must not statically link class-library transformation helpers from its parent
loader or silently add dependencies to the measured buildscript graph.

The repair resolves only the three existing JCL proof helpers through
`DependencyInfo.getClassLoader()`, authenticates their entire locked classlib JAR
before reflective initialization, and uses that same explicit loader chain for
the existing runtime/donor entries. It does not consult the ambient context
loader, add runtime exemptions, or change the 42-entry proof inventory. The
original method/body/layout certificates, managed-entry boundary, exact three
finder/thirteen production replacement classes and resource limits remain.

`CheckpointClassloaderControl` now runs the same twenty real frontend cases in
both modes with the class library and platform JARs in a separate child loader.
It asserts that the parent cannot load the JCL helpers and that the finder is
still owned by the parent. A further pair changes only a ZIP local-header
timestamp in the classlib archive: the archive length and class bodies are
unchanged, but the corrected proof must refuse the changed archive identity.
The original compiler must accept that finite-initializer control. Exceptions
are propagated, temporary inputs are removed, and the ambient context loader is
restored after the fixture.

The fast qualifier retains these results in `classloaderControls` and includes
the launcher source in its bounded input archive. Its existing twenty-case
flat-classpath controls, context and monitor controls still run independently.
The original split-loader crash and repaired controls were replayed locally with
the locked TeaVM JARs, OpenJDK 21, and `--release 21` fixtures; generated finder
classes used `--release 11`. These local controls do not substitute for a fresh
pinned hosted build or signed-runtime qualification of the repaired source.

## Local route checks

From a checkout with the repository's Python dependencies installed:

```sh
python3 -B -m unittest tools.tests.test_java_progress_workflow -v
```

These checks compare the workflow with both reviewed job contracts and protect
the exact branch/prerequisite, original JVM job, native acquisition, fresh build
command, immutable action pins, credential boundary and selected evidence paths.
They do not execute the guest compiler or claim signed runtime success.
