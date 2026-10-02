#!/usr/bin/env python3
"""Prepare an actual opt-in fiber component and unchanged reference JDK control.

Signed node execution is a separate selected test; this compiler receipt alone
does not qualify the complete Java standard concurrency profile.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time

sys.dont_write_bytecode = True
if __package__ in (None, ""): sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.java_guest.compiler import Compiler
from tools.rust_capsule_project import ROOT, digest, fresh, read_file, write_json


def locked_model_classpath(compiler: Compiler, *, include_platform: bool = False) -> tuple[str, dict[str, str]]:
    """Verify the compiler's own locked model tooling before any host loading."""
    names = {"teavm-classlib", "teavm-core", "teavm-extension-spi", "teavm-interop",
             "teavm-relocated-libs-asm", "teavm-relocated-libs-asm-analysis",
             "teavm-relocated-libs-asm-commons", "teavm-relocated-libs-asm-tree", "teavm-relocated-libs-hppc"}
    if include_platform: names.add("teavm-platform")
    lock = json.loads(read_file(compiler.sdk / "feasibility/dependencies.lock.json"))
    artifacts = [item for item in lock["artifacts"]
                 if Path(item["path"]).parts[-3] in names and item["path"].startswith("org/teavm/")]
    if (len(artifacts) != len(names) or {Path(item["path"]).parts[-3] for item in artifacts} != names):
        raise ValueError("Java runtime model requires the exact locked tooling closure")
    cache = getattr(compiler, "dependency_cache", compiler.directory / "gradle-home/caches/modules-2/files-2.1")
    jars, identities = [], {}
    for item in sorted(artifacts, key=lambda row: row["path"]):
        parts = Path(item["path"]).parts
        candidates = list((cache / ".".join(parts[:-3]) / parts[-3] / parts[-2]).glob("*/" + parts[-1]))
        if len(candidates) != 1: raise ValueError("Java runtime model tooling jar is missing or ambiguous")
        raw = read_file(candidates[0], 25 * 1024 * 1024)
        if len(raw) != item["size"] or hashlib.sha256(raw).hexdigest() != item["sha256"]:
            raise ValueError("Java runtime model tooling jar integrity mismatch")
        jars.append(candidates[0])
        identities[item["path"]] = item["sha256"]
    return os.pathsep.join(map(str, jars)), identities


def throwable_model_control(compiler: Compiler, output: Path) -> dict:
    """Test the actual locked classlib IR, without loading application classes."""
    classpath, identities = locked_model_classpath(compiler)
    output.mkdir()
    compiler.run("throwable-model-compile", "javac", "-proc:none", "--release", "25", "-cp", classpath,
                 "-d", output,
                 compiler.sdk / "fibers/compiler/dev/latent/guest/runtime/compiler/ThrowableInitialization.java",
                 compiler.sdk / "fibers/conformance/compiler/ThrowableInitializationControl.java")
    result = compiler.run("throwable-model-control", "java", "-Xmx256m", "-cp",
                          str(output) + os.pathsep + classpath,
                          "dev.latent.guest.runtime.compiler.ThrowableInitializationControl")
    expected = ("THROWABLE_INITIALIZATION_CONTROL PASS constructors=5;original-negative;real-array-initializer;"
                "method-owners;layout-and-repeated-port-negatives;application-identity")
    if result.strip() != expected: raise ValueError("Java Throwable model control did not complete")
    return {"status": "actual-locked-classlib-model-passed", "constructors": 5, "jarDigests": identities}


def timeunit_model_control(compiler: Compiler, output: Path) -> dict:
    """Prove the standard enum body port and conversion observables separately."""
    classpath, identities = locked_model_classpath(compiler)
    output.mkdir()
    sources = ("fibers/dev/latent/guest/runtime/concurrent/TimeUnit.java",
               "fibers/compiler/dev/latent/guest/runtime/compiler/RuntimeSubstitution.java",
               "fibers/compiler/dev/latent/guest/runtime/compiler/TimeUnitMethods.java",
               "fibers/conformance/compiler/TimeUnitModelControl.java",
               "fibers/conformance/compiler/TimeUnitNativeControl.java")
    compiler.run("timeunit-model-compile", "javac", "-proc:none", "--release", "25", "-cp", classpath,
                 "-d", output, *(compiler.sdk / source for source in sources))
    result = compiler.run("timeunit-model-control", "java", "-Xmx256m", "-cp",
                          str(output) + os.pathsep + classpath,
                          "dev.latent.guest.runtime.compiler.TimeUnitModelControl").strip()
    expected = ("TIMEUNIT_MODEL_CONTROL PASS missing-declarations-negative;standard-body-and-reference-closure;"
                "enum-owners-preserved;layout-negative;application-identity-preserved bodies=")
    bodies = result.removeprefix(expected)
    if not result.startswith(expected) or not bodies.isdecimal() or not 16 <= int(bodies) <= 256:
        raise ValueError("Java TimeUnit model control did not complete")
    native = compiler.run("timeunit-native-control", "java", "-Xmx256m", "-cp", output,
                          "TimeUnitNativeControl").strip()
    if native != "TIMEUNIT_NATIVE_SOURCE_CONTROL PASS checks=1661":
        raise ValueError("Java TimeUnit reference conversion control did not complete")
    return {"status": "actual-locked-classlib-model-passed", "methodBodies": int(bodies),
            "referenceConversionChecks": 1661, "jarDigests": identities}


def wait_frame_model_control(compiler: Compiler, output: Path) -> dict:
    """Verify the actual native/callback pairs and their resumed owner frames."""
    classpath, identities = locked_model_classpath(compiler, include_platform=True)
    output.mkdir()
    sources = ("fibers/compiler/dev/latent/guest/runtime/compiler/RuntimePlugin.java",
               "fibers/compiler/dev/latent/guest/runtime/compiler/RuntimeSubstitution.java",
               "fibers/compiler/dev/latent/guest/runtime/compiler/TimeUnitMethods.java",
               "fibers/compiler/dev/latent/guest/runtime/compiler/ThrowableInitialization.java",
               "fibers/compiler/dev/latent/guest/runtime/compiler/ContinuationProgram.java",
               "fibers/compiler/dev/latent/guest/runtime/compiler/MonitorContinuations.java",
               "fibers/compiler/dev/latent/guest/runtime/compiler/SynchronizedMethods.java",
               "fibers/compiler/dev/latent/guest/runtime/compiler/SleepContinuations.java",
               "fibers/compiler/dev/latent/guest/runtime/compiler/WaitContinuations.java",
               "fibers/conformance/compiler/WaitFramePluginOrder.java",
               "fibers/conformance/compiler/WaitFrameModelControl.java")
    compiler.run("wait-frame-model-compile", "javac", "-proc:none", "--release", "25", "-cp", classpath,
                 "-d", output, *(compiler.sdk / source for source in sources))
    result = compiler.run("wait-frame-model-control", "java", "-Xmx256m", "-cp",
                          str(output) + os.pathsep + classpath,
                          "dev.latent.guest.runtime.compiler.WaitFrameModelControl").strip()
    expected = ("WAIT_FRAME_MODEL_CONTROL PASS original-native-negative;real-native-callback-pairs;"
                "resumed-java-frame-owners;throws-and-standard-owners;actual-platform-order;"
                "async-lowered-owned-pairs;platform-first-negative;shape-and-repeat-negatives;application-identity;"
                "coroutine-wrappers=6;coroutine-monitors=2;coroutine-native-pairs=2;entry-layout-negative")
    if result != expected: raise ValueError("Java wait frame model control did not complete")
    return {"status": "actual-locked-classlib-model-passed", "nativeCallbackPairs": 2,
            "pluginOrder": ["runtime", "platform"], "asyncLoweredOwnedPairs": 2,
            "coroutineWrappers": 6, "coroutineMonitors": 2, "coroutineNativePairs": 2, "jarDigests": identities}


def completable_source_control(compiler: Compiler, output: Path) -> dict:
    """Compare standard observables and execute port ownership with a private host ledger.

    The test ledger is never compiled into the component. These receipts establish
    host source behavior; the actual managed pool, continuations and guest bindings
    still require normal signed component execution.
    """
    fixture = compiler.sdk / "fibers/conformance/compiler"
    native = fixture / "CompletableFutureNativeControl.java"
    owners = fixture / "CompletableFutureOwnerControl.java"
    executor_reference = fixture / "CompletableFutureExecutorThrowReferenceControl.java"
    executor_owners = fixture / "CompletableFutureExecutorAcceptanceOwnerControl.java"
    uncertain_owners = fixture / "CompletableFutureExecutorUncertainOwnerControl.java"
    stubs = [fixture / "source-control" / name for name in (
        "PrivateSourceRunner.java", "dev/latent/generated/Bindings.java",
        "dev/latent/guest/runtime/Activation.java", "dev/latent/guest/runtime/concurrent/Executors.java")]
    ports = [compiler.sdk / ("fibers/dev/latent/guest/runtime/concurrent/" + name + ".java")
             for name in ("CompletableFuture", "CompletionStage", "CompletionException")]
    inputs = {path.relative_to(compiler.sdk).as_posix(): digest(read_file(path))
              for path in (native, owners, executor_reference, executor_owners, uncertain_owners, *stubs, *ports)}
    output.mkdir()
    reference, private = output / "reference", output / "private"
    reference.mkdir(); private.mkdir()
    compiler.run("completable-reference-compile", "javac", "-proc:none", "--release", "25", "-d", reference,
                 native, executor_reference)
    expected = "COMPLETABLE_FUTURE_SOURCE_CONTROL PASS observables=82"
    observed = compiler.run("completable-reference-run", "java", "-Xmx256m", "-cp", reference,
                            "CompletableFutureNativeControl").strip()
    if observed != expected: raise ValueError("Java CompletableFuture reference control did not complete")
    executor_expected = compiler.run("completable-executor-reference-run", "java", "-Xmx256m", "-cp", reference,
                                     "CompletableFutureExecutorThrowReferenceControl").strip()
    executor_cases = [json.loads(line) for line in executor_expected.splitlines()]
    if len(executor_cases) != 6: raise ValueError("Java CompletableFuture executor reference cases did not complete")
    text = read_file(native).decode("utf-8")
    for name in ("CompletableFuture", "CompletionStage", "CompletionException"):
        original = "import java.util.concurrent." + name + ";"
        if text.count(original) != 1: raise ValueError("Java CompletableFuture source control import is ambiguous")
        text = text.replace(original, "import dev.latent.guest.runtime.concurrent." + name + ";")
    # The original public JDK cases remain unchanged. The private ledger's
    # immediate-retirement case must use an actual SDK-owned rejection witness,
    # rather than infer physical absence from an arbitrary executor exception.
    rejection = 'Executor reject = command -> { throw new RejectedExecutionException("source-control-denied"); };'
    if text.count(rejection) != 1: raise ValueError("Java CompletableFuture rejection fixture is ambiguous")
    text = text.replace(rejection, "Executor reject = dev.latent.guest.runtime.concurrent.Executors.rejected();")
    private_native = private / native.name
    private_native.write_text(text, encoding="utf-8")
    text = read_file(executor_reference).decode("utf-8")
    for name in ("CompletableFuture", "CompletionException"):
        original = "import java.util.concurrent." + name + ";"
        if text.count(original) != 1: raise ValueError("Java CompletableFuture executor control import is ambiguous")
        text = text.replace(original, "import dev.latent.guest.runtime.concurrent." + name + ";")
    private_executor = private / executor_reference.name
    private_executor.write_text(text, encoding="utf-8")
    compiler.run("completable-source-compile", "javac", "-proc:none", "--release", "25", "-d", private,
                 private_native, private_executor, owners, executor_owners, uncertain_owners, *stubs, *ports)
    owner_result = "COMPLETABLE_FUTURE_OWNER_CONTROL PASS observables=419;raceRounds=32"
    observed = compiler.run("completable-source-run", "java", "-Xmx256m", "-cp", private,
                            "PrivateSourceRunner").strip()
    if observed.splitlines() != [expected, owner_result]:
        raise ValueError("Java CompletableFuture source ownership controls did not complete")
    executor_observed = compiler.run("completable-executor-source-run", "java", "-Xmx256m", "-cp", private,
                                     "CompletableFutureExecutorThrowReferenceControl").strip()
    if [json.loads(line) for line in executor_observed.splitlines()] != executor_cases:
        raise ValueError("Java CompletableFuture executor behavior differs from the actual reference JDK")
    observed = compiler.run("completable-executor-owners-run", "java", "-Xmx256m", "-cp", private,
                            "CompletableFutureExecutorAcceptanceOwnerControl").strip()
    if observed != "COMPLETABLE_FUTURE_EXECUTOR_ACCEPTANCE_OWNER PASS observables=49":
        raise ValueError("Java CompletableFuture executor acceptance ownership controls did not complete")
    observed = compiler.run("completable-executor-uncertain-run", "java", "-Xmx256m", "-cp", private,
                            "CompletableFutureExecutorUncertainOwnerControl").strip()
    if observed != ("COMPLETABLE_FUTURE_EXECUTOR_UNCERTAIN_OWNER PASS observables=30;"
                    "queued=8;results=8;cleanup-denied;activation-retirement-unqualified"):
        raise ValueError("Java CompletableFuture uncertain executor capacity control did not complete")
    if inputs != {name: digest(read_file(compiler.sdk / name)) for name in inputs}:
        raise ValueError("Java CompletableFuture control inputs changed during execution")
    return {"status": "reference-and-SDK-source-controls-passed", "referenceObservables": 82,
            "sourceOwnershipObservables": 419, "raceRounds": 32, "sourceInputs": inputs,
            "executorReferenceCases": 6, "executorAcceptanceOwnershipObservables": 49,
            "uncertainExecutorOwnershipObservables": 30,
            "uncertainAcceptanceAtOriginalOwnerCapacity": True, "uncertainActivationRetirementQualified": False,
            "componentExecutionPerformed": False, "actualGuestBindingsUsed": False}


def completable_model_control(compiler: Compiler, output: Path) -> dict:
    """Check canonical class identities, emitted callbacks and owned continuations.

    Private host ledger declarations make this model readable; its code and the
    application classes are never initialized. The locked lambda emitter checks
    every callback declared by the port; guest bindings and the application
    callback graph still require separate component qualification.
    """
    classpath, identities = locked_model_classpath(compiler, include_platform=True)
    output.mkdir()
    sources = [*sorted((compiler.sdk / "fibers/compiler/dev/latent/guest/runtime/compiler").glob("*.java")),
               compiler.sdk / "fibers/conformance/compiler/CompletableFutureModelControl.java"]
    sources += [compiler.sdk / ("fibers/dev/latent/guest/runtime/concurrent/" + name + ".java")
                for name in ("CompletableFuture", "CompletionStage", "CompletionException", "Future", "TimeUnit")]
    sources += [compiler.sdk / ("fibers/conformance/compiler/source-control/" + name) for name in (
        "dev/latent/generated/Bindings.java", "dev/latent/guest/runtime/Activation.java",
        "dev/latent/guest/runtime/concurrent/Executors.java", "org/teavm/dependency/LambdaEmitterControlContext.java")]
    compiler.run("completable-model-compile", "javac", "-proc:none", "--release", "25", "-cp", classpath,
                 "-d", output, *sources)
    expected = ("COMPLETABLE_FUTURE_MODEL_CONTROL PASS actual-missing-class-negative;canonical-api-and-helper-identities;"
        "resolved-reference-closure;unsupported-no-fallback;actual-coroutine-monitors=24;owned-callback-bodies=25;"
        "bodies=180;actual-generated-callbacks=23;application-identity")
    observed = compiler.run("completable-model-control", "java", "-Xmx256m", "-cp",
                            str(output) + os.pathsep + classpath,
                            "dev.latent.guest.runtime.compiler.CompletableFutureModelControl").strip()
    if observed != expected: raise ValueError("Java CompletableFuture model control did not complete")
    return {"status": "actual-locked-classlib-model-passed", "modelMethodBodies": 180,
            "coroutineMonitorBodies": 24, "ownedCallbackBodies": 25, "actualGeneratedCallbacks": 23,
            "jarDigests": identities,
            "portOrApplicationClassesInitialized": False, "actualGuestBindingsUsed": False}


def recipe_inputs() -> dict[str, str]:
    paths = [Path(__file__), *sorted((ROOT / "tools/java_guest").glob("*.py")),
             ROOT / "tools/stage_runtime_wit.py", ROOT / "tools/rust_capsule_project.py",
             ROOT / "tools/build_observation.py", ROOT / "tools/build_process.py",
             ROOT / "tools/build_process_linux.py", ROOT / "tools/build_process_windows.py"]
    return {path.relative_to(ROOT).as_posix(): digest(read_file(path)) for path in paths}


def prepare(output: Path, wasi_sdk: Path, *, gradle="gradle", offline_cache: Path | None = None,
            read_only_cache: Path | None = None, fixture="threads"):
    if fixture not in {"threads", "completable"}: raise ValueError("unknown Java fiber fixture")
    if offline_cache is not None and read_only_cache is not None:
        raise ValueError("Java dependency cache selections are mutually exclusive")
    output = fresh(output)
    common = ROOT / "sdk/java-guest/fibers/conformance"
    selected = common if fixture == "threads" else common / "completable"
    # Exercise real source attribution independently of package-directory layout.
    source = output / "src/Capsule.java"
    source.parent.mkdir(parents=True)
    source.write_bytes(read_file(selected / "Capsule.java"))
    wit = output / "wit/service.wit"
    wit.parent.mkdir()
    wit.write_bytes(read_file(common / "service.wit"))
    started = time.monotonic()
    before = recipe_inputs()
    report = {"formatVersion": 1, "profile": "teavm-activation-fibers-v1", "qualification": "pending",
              "status": "running", "nodeExecution": "not-run", "sourceDigest": digest(source.read_bytes()),
              "fixture": fixture}
    report["recipeInputs"] = before
    try:
        compiler = Compiler(output / "compiler", wasi_sdk, gradle=gradle, offline_cache=offline_cache,
                            read_only_cache=read_only_cache, timeout=1200)
        control = output / "reference-jdk"
        control.mkdir()
        main = control / "Main.java"
        main.write_bytes(read_file(selected / "Main.java"))
        compiler.paths["javac"] = compiler.paths["java"].parent / "javac"
        compiler.run("reference-jdk-compile", "javac", "-proc:none", "-d", control, source, main)
        report["reference"] = []
        for iteration in range(3):
            result = compiler.run(f"reference-jdk-{iteration}", "java", "-cp", control, "Main")
            if result.strip() != "42 42 42 42": raise ValueError("reference-JDK fiber observable mismatch")
            report["reference"].append({"iteration": iteration, "modes": [0, 1, 2, 3], "results": [42, 42, 42, 42]})
        report["completableSource"] = completable_source_control(compiler, output / "completable-source")
        component, report["record"] = compiler.compile(output / "src", wit.parent,
            "tests:caller/service@1.0.0", output / "build", activation_profile=True)
        report["throwableModel"] = throwable_model_control(compiler, output / "throwable-model")
        report["timeunitModel"] = timeunit_model_control(compiler, output / "timeunit-model")
        report["waitFrameModel"] = wait_frame_model_control(compiler, output / "wait-frame-model")
        report["completableModel"] = completable_model_control(compiler, output / "completable-model")
        compiler.check_unchanged()
        report["sdkInputs"] = {name: digest(data) for name, data in compiler.original_sdk.items()}
        report["componentDigest"] = digest(read_file(component, 64 * 1024 * 1024))
        compiler.check_unchanged()
        if recipe_inputs() != before: raise ValueError("Java fiber qualification recipe changed during preparation")
        report["commands"] = compiler.records
        (output / "compiler-inputs.json").write_bytes(compiler.compiler_inputs)
        report["status"] = "component-built-unqualified"
    except BaseException as error:
        report.update(status="failed", reason=str(error))
        raise
    finally:
        report["seconds"] = round(time.monotonic() - started, 6)
        write_json(output / "FIBERS-COMPILE.json", report)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--wasi-sdk", type=Path, required=True)
    parser.add_argument("--gradle", default="gradle")
    caches = parser.add_mutually_exclusive_group()
    caches.add_argument("--offline-cache", type=Path)
    caches.add_argument("--read-only-cache", type=Path)
    parser.add_argument("--fixture", choices=("threads", "completable"), default="threads")
    args = parser.parse_args()
    prepare(args.output, args.wasi_sdk, gradle=args.gradle, offline_cache=args.offline_cache,
            read_only_cache=args.read_only_cache, fixture=args.fixture)


if __name__ == "__main__": main()
