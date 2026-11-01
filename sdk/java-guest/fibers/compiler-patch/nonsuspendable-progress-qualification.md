# Non-suspendable progress: fresh runtime qualification

PR #1588 adds a final-reachability refusal for unsupported progress in class
initializers and unmanaged contexts. The JVM controls and a signed component
exercise different boundaries; neither may stand in for the other.

## Owning workflow

`.github/workflows/java-checkpoint-context.yml` retains the original
`compiler-context` job, its exact inputs, timeout, and branch route. Its
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

The first execution of this added job is pending when this guide is introduced.
Even a successful focused GC programme does not close every #741 requirement:
independent lifecycle, timer, socket and general preemption coverage remain
subject to their own evidence.

## Local route checks

From a checkout with the repository's Python dependencies installed:

```sh
python3 -B -m unittest tools.tests.test_java_progress_workflow -v
```

These checks compare the workflow with both reviewed job contracts and protect
the exact branch/prerequisite, original JVM job, native acquisition, fresh build
command, immutable action pins, credential boundary and selected evidence paths.
They do not execute the guest compiler or claim signed runtime success.
