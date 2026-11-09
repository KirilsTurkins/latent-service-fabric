#!/usr/bin/env python3
"""Prepare an actual opt-in fiber component and unchanged reference JDK control.

Signed node execution is a separate selected test; this compiler receipt alone
does not qualify the complete Java standard concurrency profile.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import time

sys.dont_write_bytecode = True
if __package__ in (None, ""): sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.java_guest.compiler import Compiler, source_module
from tools.rust_capsule_project import ROOT, digest, fresh, read_file, write_json


def locked_model_classpath(compiler: Compiler, *, include_platform: bool = False,
                           include_dependency_analysis: bool = False) -> tuple[str, dict[str, str]]:
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
    if include_dependency_analysis:
        # The reviewed inventory also covers unused Gradle configurations. The
        # C compiler resolves only its own closure; an offline model must use
        # that verified closure rather than demand unrelated browser tooling.
        jar_count, jar_bytes = 0, 0
        for path in cache.glob("*/*/*/*/*.jar"):
            jar_count += 1
            jar_bytes += path.stat().st_size
            if jar_count > 96 or jar_bytes > 32 * 1024 * 1024:
                raise ValueError("Java compiler graph requires a bounded locked tooling closure")
        dependencies = source_module(compiler.sdk / "tools/dependencies.py")
        observed = dependencies.cache_inventory(cache)
        dependencies.verify_inventory(observed, lock, compiler.sdk / "feasibility/gradle/verification-metadata.xml")
        required = {item["path"] for item in artifacts}
        artifacts = observed["artifacts"]
        missing = required - {item["path"] for item in artifacts}
        if missing:
            raise ValueError("Java runtime model tooling jar is missing: " + sorted(missing)[0])
        if not artifacts or len(artifacts) > 96 or sum(item["size"] for item in artifacts) > 32 * 1024 * 1024:
            raise ValueError("Java compiler graph requires a bounded locked tooling closure")
    jars, identities = [], {}
    for item in sorted(artifacts, key=lambda row: row["path"]):
        parts = Path(item["path"]).parts
        candidates = list((cache / ".".join(parts[:-3]) / parts[-3] / parts[-2]).glob("*/" + parts[-1]))
        if len(candidates) != 1:
            raise ValueError("Java runtime model tooling jar is missing or ambiguous: " + item["path"])
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


def timer_teardown_projection(source: str) -> str:
    """Add test-only scheduling hooks to an exact copied Activation source."""
    points = (
        ("    private static void finishInvocation() {\n        finishingInvocation = true;\n"
         "        fencePendingTimerStops();\n", "        TeardownHooks.afterSample();\n"),
        ("            if (stopPending) {\n", "            TeardownHooks.beforeStopPublication();\n"),
        ("            var continuation = Option.some(work.token);\n", "            TeardownHooks.beforeAdmission();\n"),
    )
    for point, hook in points:
        if source.count(point) != 1:
            raise ValueError("Java timer teardown projection source drift")
        if "if (stopPending)" in point:
            source = source.replace(point, hook + point, 1)
        else:
            source = source.replace(point, point + hook, 1)
    return source


def timer_teardown_source_control(compiler: Compiler, output: Path, classpath: str) -> None:
    """Host JDK source projections only; not signed guest or physical retirement proof."""
    fixture = compiler.sdk / "fibers/conformance/compiler/timer-source-control"
    activation = compiler.sdk / "fibers/dev/latent/guest/runtime/Activation.java"
    sources = [compiler.sdk / name for name in (
        "runtime/dev/latent/guest/Option.java", "runtime/dev/latent/guest/Unsigned64.java",
        "fibers/dev/latent/guest/runtime/HostCalls.java", "fibers/dev/latent/guest/runtime/Monitors.java")]
    sources += [fixture / name for name in (
        "dev/latent/generated/Bindings.java", "dev/latent/guest/runtime/TeardownHooks.java",
        "TimerTeardownProjectionControl.java", "TimerTeardownRaceControl.java",
        "TimerStopPrepublicationControl.java", "TimerAdmissionRaceControl.java")]
    inputs = {str(path): digest(read_file(path)) for path in (activation, *sources)}
    output.mkdir()
    projected = output / "Activation.java"
    projected.write_text(timer_teardown_projection(read_file(activation).decode("utf-8")), encoding="utf-8")
    classes = output / "classes"
    classes.mkdir()
    compiler.run("timer-teardown-projection-compile", "javac", "-proc:none", "--release", "25",
                 "-cp", classpath, "-d", classes, projected, *sources)
    result = compiler.run("timer-teardown-projection-control", "java", "-Xmx256m", "-cp",
                          str(classes) + os.pathsep + classpath, "TimerTeardownProjectionControl")
    expected = ["TIMER_TEARDOWN_CONTROL PASS " + mode for mode in ("race", "exceptional", "clean", "closed-before")]
    expected += ["TIMER_STOP_PREPUBLICATION PASS retained;no-host-stop"]
    expected += ["TIMER_ADMISSION_RACE PASS " + mode for mode in ("exceptional", "clean")]
    expected += ["TIMER_TEARDOWN_PROJECTED PASS cases=7"]
    if result.strip().splitlines() != expected:
        raise ValueError("Java timer teardown projection did not complete")
    if inputs != {str(path): digest(read_file(path)) for path in (activation, *sources)}:
        raise ValueError("Java timer teardown control inputs changed during execution")


def timer_post_ack_projection(source: str) -> str:
    """Inject failure hooks only into an exact copied Activation source."""
    points = (
        ("            ((Lease)timer).token = started.value();\n", "            PostAckHooks.afterAccept();\n"),
        ("            timers.add(timer);\n", "            PostAckHooks.afterList();\n"),
    )
    for point, hook in points:
        if source.count(point) != 1:
            raise ValueError("Java timer post-ack projection source drift")
        source = source.replace(point, point + hook, 1)
    point = "            timers.add(timer);\n"
    source = source.replace(point, "            PostAckHooks.beforeList();\n" + point, 1)
    allocation = "        TimerLease timer = new TimerLease(null, work, deadline);\n"
    if source.count(allocation) != 1:
        raise ValueError("Java timer post-ack projection source drift")
    source = source.replace(allocation, "        PostAckHooks.beforeAllocation();\n" + allocation, 1)
    return source


def timer_post_ack_source_control(compiler: Compiler, output: Path, classpath: str) -> None:
    """Private host-JDK ledger and injected ordering; no guest or retirement claim."""
    fixture = compiler.sdk / "fibers/conformance/compiler/timer-post-ack-control"
    activation = compiler.sdk / "fibers/dev/latent/guest/runtime/Activation.java"
    sources = [compiler.sdk / name for name in (
        "runtime/dev/latent/guest/Option.java", "runtime/dev/latent/guest/Unsigned64.java",
        "fibers/dev/latent/guest/runtime/HostCalls.java", "fibers/dev/latent/guest/runtime/Monitors.java")]
    sources += [fixture / name for name in (
        "dev/latent/generated/Bindings.java", "dev/latent/guest/runtime/PostAckHooks.java",
        "TimerPostAckControl.java", "TimerPostAckProjectionControl.java")]
    inputs = {str(path): digest(read_file(path)) for path in (activation, *sources)}
    output.mkdir()
    projected = output / "Activation.java"
    projected.write_text(timer_post_ack_projection(read_file(activation).decode("utf-8")), encoding="utf-8")
    classes = output / "classes"
    classes.mkdir()
    compiler.run("timer-post-ack-projection-compile", "javac", "-proc:none", "--release", "25",
                 "-cp", classpath, "-d", classes, projected, *sources)
    result = compiler.run("timer-post-ack-projection-control", "java", "-Xmx256m", "-cp",
                          str(classes) + os.pathsep + classpath, "TimerPostAckProjectionControl")
    modes = ("normal", "refused-start", "allocation-before-admission", "missing-token",
             "before-list", "list-allocation-failure", "after-list", "nested-failures", "nested-after-list")
    expected = ["TIMER_POST_ACK_CONTROL PASS " + mode for mode in modes]
    expected += ["TIMER_POST_ACK_PROJECTED PASS cases=9"]
    if result.strip().splitlines() != expected:
        raise ValueError("Java timer post-ack projection did not complete")
    if inputs != {str(path): digest(read_file(path)) for path in (activation, *sources)}:
        raise ValueError("Java timer post-ack control inputs changed during execution")


def timer_start_admission_projection(source: str) -> str:
    """Inject reentry hooks into the exact start-admission source copy."""
    points = (
        ("        TimerLease timer = new TimerLease(null, work, deadline);\n", "        TimerStartHooks.allocation();\n", False),
        ("            long now = monotonicMillis();\n", "            TimerStartHooks.clock();\n", True),
        ("            timers.add(timer);\n", "            TimerStartHooks.list();\n", False),
        ("        return threads.get(thread);\n", "        TimerStartHooks.lookup();\n", True),
        ("                var refusal = new IllegalStateException(\"activation-runtime-settle-\" + settled.error());\n",
         "                TimerStartHooks.refusal();\n", True),
    )
    for point, hook, before in points:
        if source.count(point) != 1:
            raise ValueError("Java timer start-admission projection source drift")
        source = source.replace(point, hook + point if before else point + hook, 1)
    return source


def timer_start_admission_source_control(compiler: Compiler, output: Path, classpath: str) -> None:
    """Private host ledger with injected reentry, not signed guest evidence."""
    fixture = compiler.sdk / "fibers/conformance/compiler/timer-post-ack-control"
    activation = compiler.sdk / "fibers/dev/latent/guest/runtime/Activation.java"
    sources = [compiler.sdk / name for name in (
        "runtime/dev/latent/guest/Option.java", "runtime/dev/latent/guest/Unsigned64.java",
        "fibers/dev/latent/guest/runtime/HostCalls.java", "fibers/dev/latent/guest/runtime/Monitors.java")]
    sources += [fixture / name for name in (
        "dev/latent/generated/Bindings.java", "dev/latent/guest/runtime/TimerStartHooks.java",
        "TimerStartAdmissionControl.java", "TimerStartAdmissionProjectionControl.java")]
    inputs = {str(path): digest(read_file(path)) for path in (activation, *sources)}
    output.mkdir()
    projected = output / "Activation.java"
    projected.write_text(timer_start_admission_projection(read_file(activation).decode("utf-8")), encoding="utf-8")
    classes = output / "classes"
    classes.mkdir()
    compiler.run("timer-start-admission-projection-compile", "javac", "-proc:none", "--release", "25",
                 "-cp", classpath, "-d", classes, projected, *sources)
    result = compiler.run("timer-start-admission-projection-control", "java", "-Xmx256m", "-cp",
                          str(classes) + os.pathsep + classpath, "TimerStartAdmissionProjectionControl")
    modes = ("normal", "refusal", "lost-start", "inflight-root", "inflight-worker", "same-work",
             "same-work-post-list", "nested-distinct", "overflow", "settle-before-start", "settle-refusal-retry",
             "settle-lost-ack", "settle-refusal-reentry", "allocation-root", "lookup-root", "preparation-root", "preparation-same-work")
    expected = ["START_ADMISSION_CANDIDATE PASS " + mode for mode in modes]
    expected += ["START_ADMISSION_PROJECTED PASS cases=17"]
    if result.strip().splitlines() != expected:
        raise ValueError("Java timer start-admission projection did not complete")
    if inputs != {str(path): digest(read_file(path)) for path in (activation, *sources)}:
        raise ValueError("Java timer start-admission control inputs changed during execution")


def wait_frame_model_control(compiler: Compiler, output: Path) -> dict:
    """Verify the actual native/callback pairs and their resumed owner frames."""
    classpath, identities = locked_model_classpath(compiler, include_platform=True)
    output.mkdir()
    sources = ("fibers/compiler/dev/latent/guest/runtime/compiler/RuntimePlugin.java",
               "fibers/compiler/dev/latent/guest/runtime/compiler/BoundedMathInitialization.java",
               "fibers/compiler/dev/latent/guest/runtime/compiler/EventQueueHeapMethods.java",
               "fibers/dev/latent/guest/runtime/EventQueueHeapDonor.java",
               "fibers/conformance/compiler/QueueHeapControl.java",
               "fibers/compiler/dev/latent/guest/runtime/compiler/RuntimeSubstitution.java",
               "fibers/compiler/dev/latent/guest/runtime/compiler/StandardTimerMethods.java",
               "fibers/compiler/dev/latent/guest/runtime/compiler/TimeUnitMethods.java",
               "fibers/compiler/dev/latent/guest/runtime/compiler/ThrowableInitialization.java",
               "fibers/compiler/dev/latent/guest/runtime/compiler/ContinuationProgram.java",
               "fibers/compiler/dev/latent/guest/runtime/compiler/MonitorContinuations.java",
               "fibers/compiler/dev/latent/guest/runtime/compiler/SynchronizedMethods.java",
               "fibers/conformance/compiler/TimerClaimIrControl.java",
               "fibers/compiler/dev/latent/guest/runtime/compiler/SleepContinuations.java",
               "fibers/compiler/dev/latent/guest/runtime/compiler/WaitContinuations.java",
               "fibers/conformance/compiler/WaitFramePluginOrder.java",
               "fibers/conformance/compiler/WaitFrameModelControl.java",
               "fibers/conformance/compiler/QueueDeadlineModelControl.java")
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
    queue = compiler.run("queue-deadline-model-control", "java", "-Xmx256m", "-cp",
                         str(output) + os.pathsep + classpath,
                         "dev.latent.guest.runtime.compiler.QueueDeadlineModelControl").strip()
    if queue != ("QUEUE_DEADLINE_MODEL_CONTROL PASS actual-locked-queue;first-sample-delays;"
                 "second-sample-comparison;owned-clock-hooks=2;negative-shapes=4"):
        raise ValueError("Java queue deadline model control did not complete")
    heap = compiler.run("queue-heap-control", "java", "-Xmx256m", "-cp",
                        str(output) + os.pathsep + classpath,
                        "dev.latent.guest.runtime.compiler.QueueHeapControl").strip()
    if heap != ("QUEUE_HEAP_CONTROL PASS actual-original-regression;actual-corrected-order;"
                "up;down;ties;root;single-child;signed-min;last;singleton;empty;missing;repeat;model;preimage-negative;repeat-negative;donor-body-negative;donor-layout-negative;donor-node-negative"):
        raise ValueError("Java queue heap control did not complete")
    timer_output = output / "timer-source-control"
    timer_output.mkdir()
    timer_fixture = "fibers/conformance/compiler/timer-source-control/"
    timer_sources = ("runtime/dev/latent/guest/Option.java", "runtime/dev/latent/guest/Unsigned64.java",
                     "fibers/dev/latent/guest/runtime/Activation.java", "fibers/dev/latent/guest/runtime/HostCalls.java",
                     "fibers/dev/latent/guest/runtime/Monitors.java",
                     timer_fixture + "dev/latent/generated/Bindings.java", timer_fixture + "TimerReadinessSourceControl.java")
    timer_sources += (timer_fixture + "ExecutorActivationSettlementControl.java",)
    timer_sources += tuple(path.relative_to(compiler.sdk).as_posix() for path in
        sorted((compiler.sdk / "fibers/dev/latent/guest/runtime/concurrent").glob("*.java")))
    compiler.run("timer-readiness-source-compile", "javac", "-proc:none", "--release", "25", "-cp", classpath,
                 "-d", timer_output, *(compiler.sdk / name for name in timer_sources))
    timer = compiler.run("timer-readiness-source-control", "java", "-Xmx256m", "-cp",
                         str(timer_output) + os.pathsep + classpath, "TimerReadinessSourceControl").strip()
    if timer != ("TIMER_READINESS_SOURCE_CONTROL PASS two-timer-bound;captured-frame-deadline;first-clock-latch;"
                 "stable-ties;fired-and-closing-exclusion;confirmed-stop;cancelled-ownership;zero-huge-and-fallback;managed-start-rollback;uncertain-result-fence;uncertain-queued-owner-fence;timer-stop-uncertain-completion-fence;nested-stop-count-guard;timer-finally-return-fence;timer-teardown-admission-fence"):
        raise ValueError("Java timer readiness source control did not complete")
    claim = compiler.run("timer-start-claim-ir-control", "java", "-Xmx256m", "-cp",
                         str(output) + os.pathsep + str(timer_output) + os.pathsep + classpath,
                         "dev.latent.guest.runtime.compiler.TimerClaimIrControl").strip()
    if claim != "TIMER_CLAIM_IR PASS selected-loop-positive;four-helpers-no-checkpoint-or-split-kind;not-guest":
        raise ValueError("Java timer claim IR control did not complete")
    timer_teardown_source_control(compiler, output / "timer-teardown-projection", classpath)
    timer_post_ack_source_control(compiler, output / "timer-post-ack-projection", classpath)
    timer_start_admission_source_control(compiler, output / "timer-start-admission-projection", classpath)
    executor_settlement = executor_activation_settlement_control(compiler, timer_output, classpath)
    return {"status": "actual-locked-classlib-model-passed", "nativeCallbackPairs": 2,
            "pluginOrder": ["runtime", "platform"], "asyncLoweredOwnedPairs": 2,
            "coroutineWrappers": 6, "coroutineMonitors": 2, "coroutineNativePairs": 2,
            "queueClockSamples": 2, "queueShapeNegatives": 4,
            "queueHeapControl": "actual-pinned-jvm-queue-and-model-not-guest-qualification",
            "timerReadinessSourceControl": "passed-private-source-ledger-not-guest-qualification",
            "executorActivationSettlement": executor_settlement, "jarDigests": identities}


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
               compiler.sdk / "fibers/conformance/compiler/CompletableFutureModelControl.java",
               compiler.sdk / "fibers/conformance/compiler/CompletableFutureFieldModelControl.java"]
    sources += [compiler.sdk / ("fibers/dev/latent/guest/runtime/concurrent/" + name + ".java")
                for name in ("CompletableFuture", "CompletionStage", "CompletionException", "Future", "TimeUnit")]
    sources += [compiler.sdk / ("fibers/conformance/compiler/source-control/" + name) for name in (
        "dev/latent/generated/Bindings.java", "dev/latent/guest/runtime/Activation.java",
        "dev/latent/guest/runtime/concurrent/Executors.java", "org/teavm/dependency/LambdaEmitterControlContext.java")]
    compiler.run("completable-model-compile", "javac", "-proc:none", "--release", "25", "-cp", classpath,
                 "-d", output, *sources)
    expected = ("COMPLETABLE_FUTURE_MODEL_CONTROL PASS actual-missing-class-negative;canonical-api-and-helper-identities;"
        "resolved-reference-closure;unsupported-no-fallback;result-settlement-fence;queued-settlement-fence;"
        "actual-coroutine-monitors=28;owned-callback-bodies=32;bodies=190;actual-generated-callbacks=23;application-identity")
    observed = compiler.run("completable-model-control", "java", "-Xmx256m", "-cp",
                            str(output) + os.pathsep + classpath,
                            "dev.latent.guest.runtime.compiler.CompletableFutureModelControl").strip()
    if observed != expected: raise ValueError("Java CompletableFuture model control did not complete")
    fields = compiler.run("completable-field-model-control", "java", "-Xmx256m", "-cp",
                          str(output) + os.pathsep + classpath,
                          "dev.latent.guest.runtime.compiler.CompletableFutureFieldModelControl").strip()
    if fields != ("COMPLETABLE_FUTURE_FIELD_MODEL_CONTROL PASS declared-and-inherited-types;"
                  "closed-read-write-references;absent-no-fallback;models=6"):
        raise ValueError("Java CompletableFuture field model control did not complete")
    return {"status": "actual-locked-classlib-model-passed", "modelFingerprintVersion": 5, "modelMethodBodies": 190,
            "coroutineMonitorBodies": 28, "ownedCallbackBodies": 32, "actualGeneratedCallbacks": 23,
            "jarDigests": identities,
            "fieldReferences": "actual-declared-and-inherited-types-passed",
            "portOrApplicationClassesInitialized": False, "actualGuestBindingsUsed": False}


STANDARD_TIMER_ACTIVE_OWNER_CASES = (
    "one-shot-normal", "one-shot-error", "external-cancel", "external-purge", "self-cancel", "self-purge",
    "fixed-rate-reschedule", "fixed-delay-reschedule", "refused", "lost", "callback-refused", "callback-lost",
    "periodic-callback-refused", "periodic-callback-lost", "cancel-refused", "cancel-lost",
    "callback-ack", "clear-queue-ack", "cancelled-head-ack", "purge-ack",
    "manage-before", "manage-close-refused", "manage-close-lost",
    "start-before", "start-uncertain", "start-accepted", "start-close-refused", "start-close-lost",
    "start-finished-ok", "start-finished-refused", "start-finished-lost", "public-task-monitor",
)


def standard_timer_source_control(compiler: Compiler, output: Path) -> dict:
    """Execute unchanged SDK timer sources with an explicitly private host ledger.

    The ordinary application has separate reference-JDK executions. Only this
    host control maps its imports to the SDK implementation; neither that copy
    nor its private ledger is an input to the component compiler.
    """
    fixture = compiler.sdk / "fibers/conformance"
    application = fixture / "timers/Capsule.java"
    main = fixture / "timers/Main.java"
    validation = fixture / "timers/TimerValidationOrder.java"
    private = fixture / "compiler/standard-timer-control"
    sources = [private / name for name in (
        "TimerModelMain.java", "TimerActiveOwnerControl.java", "TimerValidationAdmissionControl.java",
        "dev/latent/generated/Bindings.java", "dev/latent/guest/runtime/Activation.java")]
    clock_sources = [private / "FakeClock.java", private / "ClockOrderControl.java"]
    ports = [compiler.sdk / ("fibers/dev/latent/guest/runtime/util/" + name + ".java")
             for name in ("Timer", "TimerTask")]
    inputs = {path.relative_to(compiler.sdk).as_posix(): digest(read_file(path))
              for path in (application, main, validation, *sources, *ports, *clock_sources)}
    output.mkdir()
    mapped = output / "Capsule.java"
    text = read_file(application).decode("utf-8")
    for name in ("Timer", "TimerTask"):
        original = "import java.util." + name + ";"
        if text.count(original) != 1: raise ValueError("Java timer source control import is ambiguous")
        text = text.replace(original, "import dev.latent.guest.runtime.util." + name + ";")
    mapped.write_text(text, encoding="utf-8")
    mapped_validation = output / "TimerValidationOrder.java"
    text = read_file(validation).decode("utf-8")
    for name in ("Timer", "TimerTask"):
        original = "import java.util." + name + ";"
        if text.count(original) != 1: raise ValueError("Java timer validation control import is ambiguous")
        text = text.replace(original, "import dev.latent.guest.runtime.util." + name + ";")
    mapped_validation.write_text(text, encoding="utf-8")
    compiler.run("standard-timer-source-compile", "javac", "-proc:none", "--release", "25",
                 "-d", output, mapped, mapped_validation, main, *sources, *ports)
    expected = ["42 42 42 42",
        "TIMER_SOURCE_CONTROL PASS reference-observables;queue-rollback;cancel-drain;idle-finally;no-live-owners"]
    for iteration in range(3):
        result = compiler.run(f"standard-timer-source-{iteration}", "java", "-Xmx256m", "-cp",
                              output, "TimerModelMain")
        if result.strip().splitlines() != expected:
            raise ValueError("Java standard timer source control did not complete")
    if inputs != {name: digest(read_file(compiler.sdk / name)) for name in inputs}:
        raise ValueError("Java timer control inputs changed during execution")
    for case in STANDARD_TIMER_ACTIVE_OWNER_CASES:
        result = compiler.run("standard-timer-active-" + case, "java", "-Xmx256m", "-cp",
                              output, "TimerActiveOwnerControl", case)
        if result.strip() != "TIMER_ACTIVE_OWNER_CONTROL PASS " + case:
            raise ValueError("Java timer active-owner control did not complete: " + case)
    if inputs != {name: digest(read_file(compiler.sdk / name)) for name in inputs}:
        raise ValueError("Java timer control inputs changed during execution")
    # Replace only the clock read in a private source port to verify invalid
    # periods are rejected before the scheduler consults wall time.
    clock = output / "clock-control"
    clock.mkdir()
    timer = read_file(ports[0]).decode("utf-8")
    if timer.count("System.currentTimeMillis()") != 2:
        raise ValueError("Java timer clock control source is ambiguous")
    clock_timer = clock / "Timer.java"
    clock_timer.write_text(timer.replace("System.currentTimeMillis()", "FakeClock.currentTimeMillis()"), encoding="utf-8")
    compiler.run("standard-timer-clock-compile", "javac", "-proc:none", "--release", "25", "-d", clock,
                 clock_timer, ports[1], *clock_sources, sources[-2], sources[-1])
    result = compiler.run("standard-timer-clock-control", "java", "-Xmx256m", "-cp", clock, "ClockOrderControl")
    if result.strip() != "TIMER_CLOCK_ORDER PASS":
        raise ValueError("Java timer clock ordering control did not complete")
    if inputs != {name: digest(read_file(compiler.sdk / name)) for name in inputs}:
        raise ValueError("Java timer control inputs changed during execution")
    return {"status": "SDK-source-controls-passed", "iterations": 3, "modes": [0, 1, 2, 3],
            "sourceInputs": inputs, "validationOrder": {"observations": 35, "referenceAndSource": "passed",
                "preAdmission": "passed", "syntheticClock": "passed"},
            "componentExecutionPerformed": False, "actualGuestBindingsUsed": False}


def standard_timer_model_control(compiler: Compiler, output: Path) -> dict:
    """Resolve substituted standard APIs against actual verified TeaVM models."""
    classpath, identities = locked_model_classpath(compiler, include_platform=True, include_dependency_analysis=True)
    output.mkdir()
    sources = [*sorted((compiler.sdk / "fibers/compiler/dev/latent/guest/runtime/compiler").glob("*.java")),
        compiler.sdk / "fibers/conformance/compiler/StandardTimerModelControl.java",
        compiler.sdk / "fibers/conformance/compiler/StandardTimerCompilerGraphControl.java"]
    sources += [compiler.sdk / ("fibers/dev/latent/guest/runtime/util/" + name + ".java")
                for name in ("Timer", "TimerTask")]
    # Compile the graph against the real guest Activation. The separate host
    # source control retains its Thread.getState worker-wait witness.
    sources += [compiler.sdk / ("fibers/dev/latent/guest/runtime/" + name + ".java")
                for name in ("Activation", "HostCalls")]
    sources += [compiler.sdk / ("runtime/dev/latent/guest/" + name + ".java")
                for name in ("Option", "Unsigned64")]
    sources.append(compiler.sdk / "fibers/conformance/compiler/timer-source-control/dev/latent/generated/Bindings.java")
    inputs = {path.relative_to(compiler.sdk).as_posix(): digest(read_file(path)) for path in sources}
    compiler.run("standard-timer-model-compile", "javac", "-proc:none", "--release", "25", "-cp", classpath,
                 "-d", output, *sources)
    result = compiler.run("standard-timer-model-control", "java", "-Xmx256m", "-cp",
        str(output) + os.pathsep + classpath, "dev.latent.guest.runtime.compiler.StandardTimerModelControl").strip()
    if result != ("STANDARD_TIMER_MODEL_CONTROL PASS original-classlib-negative;layout-and-repeat-negatives;canonical-api-and-private-helper;"
                  "resolved-method-and-field-types;unsupported-no-fallback;models=3;actual-c-dependency-worker-and-callback"):
        raise ValueError("Java standard timer model control did not complete")
    if inputs != {name: digest(read_file(compiler.sdk / name)) for name in inputs}:
        raise ValueError("Java timer model control inputs changed during execution")
    return {"status": "actual-locked-classlib-model-passed", "models": 3, "jarDigests": identities,
            "sourceInputs": inputs, "portOrApplicationClassesInitialized": False, "actualGuestBindingsUsed": False}


FUTURE_CANCEL_INTERRUPT_CASES = (
    'before-runtime', 'after-runtime', 'before-error', 'after-error',
    'before-runtime-done-error', 'after-error-done-error', 'normal', 'no-interrupt',
    'pending', 'completed', 'failed',
)
FUTURE_CANCEL_SETTLEMENT_CASES = ('refused', 'lost-ack')


def future_cancel_interrupt_control(compiler: Compiler, classes: Path) -> dict:
    """Fresh JDK/source processes; never a signed component execution receipt."""
    executed = {}
    main = 'dev.latent.guest.runtime.concurrent.FutureTaskInterruptFailureControl'
    for implementation in ('jdk', 'source'):
        modes = FUTURE_CANCEL_INTERRUPT_CASES
        if implementation == 'source':
            modes += FUTURE_CANCEL_SETTLEMENT_CASES
        executed[implementation] = []
        for mode in modes:
            # Reuse the compiler's owned process runner and original deadline.
            # A fresh JVM keeps the deliberately poisoned source ledgers apart.
            result = compiler.run('future-cancel-interrupt-' + implementation + '-' + mode,
                'java', '-Xmx256m', '-cp', classes, main, implementation, mode).strip()
            if result != 'future-cancel-interrupt ' + implementation + ' ' + mode + ' passed':
                raise ValueError('Java future cancellation control did not complete: '
                    + implementation + ' ' + mode)
            executed[implementation].append(mode)
    return {'status': 'JDK-and-SDK-source-controls-passed', 'cases': executed,
        'componentExecutionPerformed': False, 'actualGuestBindingsUsed': False}


EXECUTOR_OWNER_SETTLEMENT_CASES = (
    'normal', 'denied', 'lost', 'root-normal', 'root-denied', 'root-lost',
    'reenter-caught', 'reenter-throws', 'root-reenter-caught', 'root-reenter-throws',
    'concurrent', 'root-concurrent',
    'construct-normal', 'construct-denied', 'construct-lost',
    'construct-oom-normal', 'construct-oom-denied', 'construct-oom-lost', 'construct-reentry',
)
EXECUTOR_ACTIVATION_SETTLEMENT_CASES = (
    'denied', 'lost', 'root-denied', 'root-lost',
    'construct-normal', 'construct-denied', 'construct-lost',
    'inflight-root-success', 'inflight-root-denied', 'inflight-root-lost',
)


def executor_owner_settlement_control(compiler: Compiler, classes: Path) -> dict:
    """Fresh source-port processes; the host ledger is private test code."""
    executed = {}
    for kind in ('managed', 'scheduled'):
        executed[kind] = []
        for mode in EXECUTOR_OWNER_SETTLEMENT_CASES:
            result = compiler.run('executor-owner-settlement-' + kind + '-' + mode,
                'java', '-Xmx256m', '-cp', classes, 'ExecutorOwnerSettlementControl', kind, mode).strip()
            if result != 'EXECUTOR_OWNER_SETTLEMENT PASS ' + kind + ' ' + mode:
                raise ValueError('Java executor owner settlement control did not complete: ' + kind + ' ' + mode)
            executed[kind].append(mode)
    return {'status': 'SDK-source-controls-passed', 'cases': executed,
        'componentExecutionPerformed': False, 'actualGuestBindingsUsed': False}


def executor_activation_settlement_control(compiler: Compiler, classes: Path, classpath: str) -> dict:
    """Actual Activation and pool source with a private host ledger, not guest execution."""
    executed = {}
    for kind in ('managed', 'scheduled'):
        executed[kind] = []
        for mode in EXECUTOR_ACTIVATION_SETTLEMENT_CASES:
            result = compiler.run('executor-activation-settlement-' + kind + '-' + mode,
                'java', '-Xmx256m', '-cp', str(classes) + os.pathsep + classpath,
                'ExecutorActivationSettlementControl', kind, mode).strip()
            if result != 'EXECUTOR_ACTIVATION_SETTLEMENT PASS ' + kind + ' ' + mode:
                raise ValueError('Java executor activation settlement control did not complete: ' + kind + ' ' + mode)
            executed[kind].append(mode)
    return {'status': 'SDK-activation-source-controls-passed', 'cases': executed,
        'componentExecutionPerformed': False, 'actualGuestBindingsUsed': False}


def timer_sleep_admission_source_control(compiler: Compiler, output: Path) -> dict:
    """Run the actual sleep owner against a private, two-Timer host ledger."""
    classpath, identities = locked_model_classpath(compiler, include_platform=True)
    sdk = compiler.sdk
    fixture = sdk / 'fibers/conformance/compiler/timer-source-control'
    sources = [sdk / name for name in (
        'runtime/dev/latent/guest/Option.java', 'runtime/dev/latent/guest/Unsigned64.java',
        'fibers/dev/latent/guest/runtime/Activation.java', 'fibers/dev/latent/guest/runtime/HostCalls.java',
        'fibers/dev/latent/guest/runtime/Monitors.java')]
    sources += [fixture / 'dev/latent/generated/Bindings.java', fixture / 'TimerSleepAdmissionSourceControl.java']
    sources += sorted((sdk / 'fibers/dev/latent/guest/runtime/concurrent').glob('*.java'))
    inputs = {path.relative_to(sdk).as_posix(): digest(read_file(path)) for path in sources}
    output.mkdir()
    compiler.run('timer-sleep-admission-source-compile', 'javac', '-proc:none', '--release', '25',
        '-cp', classpath, '-d', output, *sources)
    actual = compiler.run('timer-sleep-admission-source-control', 'java', '-Xmx256m', '-cp',
        str(output) + os.pathsep + classpath, 'TimerSleepAdmissionSourceControl').strip()
    if actual != 'TIMER_SLEEP_ADMISSION_SOURCE PASS typed-refusal;wait-return;same-work-retry;raw-hook-finally':
        raise ValueError('Java timer sleep admission source control did not complete')
    if inputs != {name: digest(read_file(sdk / name)) for name in inputs}:
        raise ValueError('Java timer sleep admission source inputs changed')
    return {'status': 'SDK-source-control-passed', 'sourceInputs': inputs, 'jarDigests': identities,
        'componentExecutionPerformed': False, 'actualGuestBindingsUsed': False}


def scheduled_source_control(compiler: Compiler, output: Path) -> dict:
    """Real port source with a private host ledger, never injected guest bindings."""
    private = compiler.sdk / 'fibers/conformance/compiler/scheduled-source-control'
    ports = sorted((compiler.sdk / 'fibers/dev/latent/guest/runtime/concurrent').glob('*.java'))
    controls = [private / name for name in ('ScheduledOwnerControl.java', 'ScheduledCompletableOwnerControl.java',
        'ScheduledPeriodicOwnerControl.java', 'ScheduledPeriodicRollbackSettlementControl.java',
        'ScheduledFutureResultSettlementControl.java', 'CompletableFutureResultSettlementControl.java',
        'CompletableFutureQueuedRollbackControl.java', 'CompletableFutureQueuedSettlementControl.java',
        'ManagedExecutorQueuedSettlementControl.java',
        'ScheduledQueuedSettlementControl.java', 'FutureTaskInterruptFailureControl.java',
        'ExecutorCloseInterruptControl.java', 'ExecutorOwnerSettlementControl.java',
        'ExecutorInvokeInterruptOwnerControl.java', 'ExecutorAwaitTerminationOwnerControl.java',
        'FutureTaskNullFailureOwnerControl.java', 'FutureTaskMonitorOwnerControl.java',
        'dev/latent/generated/Bindings.java', 'dev/latent/guest/runtime/Activation.java')]
    reference = private / 'ScheduledStoppedReferenceControl.java'
    periodic_reference = private / 'ScheduledPeriodicReferenceControl.java'
    invoke_reference = private / 'ExecutorInvokeInterruptReferenceControl.java'
    termination_reference = private / 'ExecutorAwaitTerminationReferenceControl.java'
    null_failure_reference = private / 'FutureTaskNullFailureReferenceControl.java'
    monitor_reference = private / 'FutureTaskMonitorReferenceControl.java'
    inputs = {path.relative_to(compiler.sdk).as_posix(): digest(read_file(path))
        for path in (*ports, *controls, reference, periodic_reference, invoke_reference, termination_reference,
                     null_failure_reference, monitor_reference)}
    output.mkdir()
    jdk_output = output / 'reference-jdk'
    jdk_output.mkdir()
    compiler.run('scheduled-stopped-reference-compile', 'javac', '-proc:none', '--release', '25',
        '-d', jdk_output, reference, periodic_reference, invoke_reference, termination_reference,
        null_failure_reference, monitor_reference)
    expected_stopped = ('SCHEDULED_STOPPED_REFERENCE PASS delayed;fixed-rate;fixed-delay;nested;future;'
        'running;shutdown;shutdown-policy;physical-runner')
    result = compiler.run('scheduled-stopped-reference-jdk', 'java', '-Xmx256m', '-cp', jdk_output,
        'ScheduledStoppedReferenceControl').strip()
    if result != expected_stopped: raise ValueError('Java stopped scheduled reference did not complete')
    expected_periodic = ('SCHEDULED_PERIODIC_REFERENCE PASS fixed-rate;fixed-delay;reentrant;failure;self-cancel;'
        'concurrent-manual;concurrent-worker;shutdown;continue-policy')
    result = compiler.run('scheduled-periodic-reference-jdk', 'java', '-Xmx256m', '-cp', jdk_output,
        'ScheduledPeriodicReferenceControl').strip()
    if result != expected_periodic: raise ValueError('Java periodic scheduled reference did not complete')
    expected_invoke = ('EXECUTOR_INVOKE_INTERRUPT PASS preinterrupted-ready;empty;zero;pending-cancel;'
        'blocked-interrupt')
    result = compiler.run('executor-invoke-interrupt-reference-jdk', 'java', '-Xmx256m', '-cp', jdk_output,
        'ExecutorInvokeInterruptReferenceControl', 'jdk').strip()
    if result != expected_invoke: raise ValueError('Java executor invoke interruption reference did not complete')
    expected_termination = 'EXECUTOR_AWAIT_TERMINATION PASS zero;negative;positive;terminated;blocked-interrupt'
    result = compiler.run('executor-await-termination-reference-jdk', 'java', '-Xmx256m', '-cp', jdk_output,
        'ExecutorAwaitTerminationReferenceControl', 'jdk').strip()
    if result != expected_termination: raise ValueError('Java executor termination reference did not complete')
    expected_null_failure = 'FUTURE_TASK_NULL_FAILURE PASS pending;null-success;terminal-noop;nonnull;blocked-getter'
    result = compiler.run('future-task-null-failure-reference-jdk', 'java', '-Xmx256m', '-cp', jdk_output,
        'FutureTaskNullFailureReferenceControl', 'jdk').strip()
    if result != expected_null_failure: raise ValueError('Java future task null failure reference did not complete')
    expected_monitor = 'FUTURE_TASK_MONITOR_REFERENCE PASS run;cancel;completed-get;executor;scheduled-cancel'
    result = compiler.run('future-task-monitor-reference-jdk', 'java', '-Xmx256m', '-cp', jdk_output,
        'FutureTaskMonitorReferenceControl').strip()
    if result != expected_monitor: raise ValueError('Java FutureTask monitor reference did not complete')
    text = read_file(reference).decode('utf-8')
    for name in ('CompletableFuture', 'FutureTask', 'ScheduledThreadPoolExecutor'):
        original = 'import java.util.concurrent.' + name + ';'
        if text.count(original) != 1: raise ValueError('Java stopped scheduled source import is ambiguous')
        text = text.replace(original, 'import dev.latent.guest.runtime.concurrent.' + name + ';')
    selected = output / 'ScheduledStoppedReferenceControl.java'
    selected.write_bytes(text.encode('utf-8'))
    text = read_file(periodic_reference).decode('utf-8')
    original = 'import java.util.concurrent.ScheduledThreadPoolExecutor;'
    if text.count(original) != 1: raise ValueError('Java periodic scheduled source import is ambiguous')
    selected_periodic = output / 'ScheduledPeriodicReferenceControl.java'
    selected_periodic.write_bytes(text.replace(original,
        'import dev.latent.guest.runtime.concurrent.ScheduledThreadPoolExecutor;').encode('utf-8'))
    text = read_file(invoke_reference).decode('utf-8')
    original = 'import java.util.concurrent.AbstractExecutorService;'
    if text.count(original) != 1: raise ValueError('Java executor invoke reference import is ambiguous')
    selected_invoke = output / 'ExecutorInvokeInterruptReferenceControl.java'
    selected_invoke.write_bytes(text.replace(original,
        'import dev.latent.guest.runtime.concurrent.AbstractExecutorService;').encode('utf-8'))
    text = read_file(termination_reference).decode('utf-8')
    original = 'import java.util.concurrent.Executors;'
    if text.count(original) != 1: raise ValueError('Java executor termination reference import is ambiguous')
    selected_termination = output / 'ExecutorAwaitTerminationReferenceControl.java'
    selected_termination.write_bytes(text.replace(original,
        'import dev.latent.guest.runtime.concurrent.Executors;').encode('utf-8'))
    text = read_file(null_failure_reference).decode('utf-8')
    original = 'import java.util.concurrent.FutureTask;'
    if text.count(original) != 1: raise ValueError('Java future task null failure reference import is ambiguous')
    selected_null_failure = output / 'FutureTaskNullFailureReferenceControl.java'
    selected_null_failure.write_bytes(text.replace(original,
        'import dev.latent.guest.runtime.concurrent.FutureTask;').encode('utf-8'))
    text = read_file(monitor_reference).decode('utf-8')
    for name in ('FutureTask', 'Executors', 'ScheduledThreadPoolExecutor'):
        original = 'import java.util.concurrent.' + name + ';'
        if text.count(original) != 1: raise ValueError('Java FutureTask monitor reference import is ambiguous')
        text = text.replace(original, 'import dev.latent.guest.runtime.concurrent.' + name + ';')
    selected_monitor = output / 'FutureTaskMonitorReferenceControl.java'
    selected_monitor.write_bytes(text.encode('utf-8'))
    compiler.run('scheduled-source-compile', 'javac', '-proc:none', '--release', '25',
        '-d', output, *ports, *controls, selected, selected_periodic, selected_invoke, selected_termination,
        selected_null_failure, selected_monitor)
    result = compiler.run('executor-invoke-interrupt-source', 'java', '-Xmx256m', '-cp', output,
        'ExecutorInvokeInterruptReferenceControl', 'source').strip()
    if result != expected_invoke: raise ValueError('Java executor invoke source differs from reference')
    result = compiler.run('executor-invoke-interrupt-owner', 'java', '-Xmx256m', '-cp', output,
        'ExecutorInvokeInterruptOwnerControl').strip()
    if result != 'EXECUTOR_INVOKE_INTERRUPT_OWNER PASS all;any;queued-until-drain;result-settled':
        raise ValueError('Java executor invoke interruption owner control did not complete')
    result = compiler.run('executor-await-termination-source', 'java', '-Xmx256m', '-cp', output,
        'ExecutorAwaitTerminationReferenceControl', 'source').strip()
    if result != expected_termination: raise ValueError('Java executor termination source differs from reference')
    result = compiler.run('executor-await-termination-owner', 'java', '-Xmx256m', '-cp', output,
        'ExecutorAwaitTerminationOwnerControl').strip()
    if result != 'EXECUTOR_AWAIT_TERMINATION_OWNER PASS managed;scheduled;owners-held-until-worker-return':
        raise ValueError('Java executor termination owner control did not complete')
    result = compiler.run('future-task-null-failure-source', 'java', '-Xmx256m', '-cp', output,
        'FutureTaskNullFailureReferenceControl', 'source').strip()
    if result != expected_null_failure: raise ValueError('Java future task null failure source differs from reference')
    result = compiler.run('future-task-null-failure-owner', 'java', '-Xmx256m', '-cp', output,
        'FutureTaskNullFailureOwnerControl').strip()
    if result != 'FUTURE_TASK_NULL_FAILURE_OWNER PASS original-result-held-until-runner-exit':
        raise ValueError('Java future task null failure owner control did not complete')
    result = compiler.run('future-task-monitor-source', 'java', '-Xmx256m', '-cp', output,
        'FutureTaskMonitorReferenceControl').strip()
    if result != expected_monitor: raise ValueError('Java FutureTask monitor source differs from reference')
    result = compiler.run('future-task-monitor-owner', 'java', '-Xmx256m', '-cp', output,
        'FutureTaskMonitorOwnerControl').strip()
    if result != 'FUTURE_TASK_MONITOR_OWNER PASS managed;active-owners;scheduled;retired-under-public-monitor':
        raise ValueError('Java FutureTask monitor ownership control did not complete')
    interrupt_control = future_cancel_interrupt_control(compiler, output)
    executor_settlement = executor_owner_settlement_control(compiler, output)
    for implementation in ('jdk', 'source'):
        for mode in ('terminated', 'drain', 'interrupted'):
            result = compiler.run('executor-close-interrupt-' + implementation + '-' + mode,
                'java', '-Xmx256m', '-cp', output, 'ExecutorCloseInterruptControl', implementation, mode).strip()
            if result != 'EXECUTOR_CLOSE_INTERRUPT PASS ' + implementation + ' ' + mode:
                raise ValueError('Java executor close interruption control did not complete')
    result = compiler.run('scheduled-source-control', 'java', '-Xmx256m', '-cp', output, 'ScheduledOwnerControl').strip()
    expected = ('SCHEDULED_OWNER_CONTROL PASS preadmission;actual-result;running-cancel-held;periodic-nonoverlap;'
        'original-error-suppresses-repeat;timed-wait-cancel-and-interrupt;shutdown-policy;factory-rollback;all-retired')
    if result != expected: raise ValueError('Java scheduled source control did not complete')
    result = compiler.run('scheduled-completable-owner-control', 'java', '-Xmx256m', '-cp', output,
        'ScheduledCompletableOwnerControl').strip()
    if result != ('SCHEDULED_COMPLETABLE_OWNER PASS rejection;inner-admission-rollback;withdrawal;action-replay;opaque;subclass;copies;'
                  'wrapper-copies;failed-readmission;cancelled-capture;deferred-future;in-flight-wrapper;stopped-worker'):
        raise ValueError('Java scheduled CompletableFuture source control did not complete')
    for path in ('rollback', 'shutdown', 'dispatch'):
        for fault in ('denied', 'lost'):
            result = compiler.run('managed-executor-queued-settlement-' + path + '-' + fault,
                'java', '-Xmx256m', '-cp', output, 'ManagedExecutorQueuedSettlementControl', path, fault).strip()
            if result != 'MANAGED_EXECUTOR_QUEUED_SETTLEMENT PASS ' + path + ' ' + fault:
                raise ValueError('Java managed executor queued settlement control did not complete')
    for path in ('preentry', 'insert-before', 'insert-after', 'requeue', 'cancel', 'reentry-model'):
        for fault in ('denied', 'lost'):
            result = compiler.run('scheduled-queued-settlement-' + path + '-' + fault,
                'java', '-Xmx256m', '-cp', output, 'ScheduledQueuedSettlementControl', path, fault).strip()
            if result != 'SCHEDULED_QUEUED_SETTLEMENT PASS ' + path + ' ' + fault:
                raise ValueError('Java scheduled queued settlement control did not complete')
    result = compiler.run('scheduled-stopped-source-control', 'java', '-Xmx256m', '-cp', output,
        'ScheduledStoppedReferenceControl').strip()
    if result != expected_stopped: raise ValueError('Java stopped scheduled source differs from reference')
    result = compiler.run('scheduled-periodic-owner-control', 'java', '-Xmx256m', '-cp', output,
        'ScheduledPeriodicOwnerControl').strip()
    if result != ('SCHEDULED_PERIODIC_OWNER PASS copies;denial;completed-failure;insertion;worker-requeue;uncertain-insertion;manual-worker;last-copy-denial;cancel;shutdown;'
                  'running-worker;managed-wrapper;opaque;subclass-reentrancy;reentrant-factory;denied-settlement-held'):
        raise ValueError('Java periodic scheduled owner control did not complete')
    for mode in ('before', 'after'):
        result = compiler.run('scheduled-periodic-rollback-settlement-' + mode, 'java', '-Xmx256m', '-cp', output,
            'ScheduledPeriodicRollbackSettlementControl', mode).strip()
        if result != 'SCHEDULED_PERIODIC_ROLLBACK_SETTLEMENT PASS ' + mode:
            raise ValueError('Java periodic rollback settlement control did not complete')
    for mode in ('refused-claim', 'unknown-claim', 'refused-readmit', 'unknown-readmit', 'success-readmit',
                 'refused-notify', 'unknown-notify', 'refused-nested', 'unknown-nested',
                 'refused-completed', 'unknown-completed', 'success-completed'):
        result = compiler.run('scheduled-future-result-settlement-' + mode, 'java', '-Xmx256m', '-cp', output,
            'ScheduledFutureResultSettlementControl', mode).strip()
        if result != 'SCHEDULED_FUTURE_RESULT_SETTLEMENT PASS ' + mode:
            raise ValueError('Java future result settlement control did not complete')
    for mode in ('refused-direct', 'unknown-direct', 'refused-multiple', 'unknown-multiple',
                 'refused-rollback', 'unknown-rollback', 'refused-running', 'unknown-running',
                 'completed-success', 'pending-replay', 'existing-action', 'reentrant-settlement'):
        result = compiler.run('completable-result-settlement-' + mode, 'java', '-Xmx256m', '-cp', output,
            'CompletableFutureResultSettlementControl', mode).strip()
        if result != 'COMPLETABLE_RESULT_SETTLEMENT PASS ' + mode:
            raise ValueError('Java CompletableFuture result settlement control did not complete')
    for mode in ('refused-completed', 'unknown-completed', 'success-completed',
                 'refused-acceptance', 'unknown-acceptance', 'success-acceptance'):
        result = compiler.run('completable-queued-rollback-' + mode, 'java', '-Xmx256m', '-cp', output,
            'CompletableFutureQueuedRollbackControl', mode).strip()
        if result != 'COMPLETABLE_QUEUED_ROLLBACK PASS ' + mode:
            raise ValueError('Java CompletableFuture queue rollback control did not complete')
    for path in ('direct', 'waiting', 'multiple', 'readmit-denied', 'readmit-completed'):
        for fault in ('denied', 'lost', 'success'):
            result = compiler.run('completable-queued-settlement-' + path + '-' + fault,
                'java', '-Xmx256m', '-cp', output, 'CompletableFutureQueuedSettlementControl', path, fault).strip()
            if result != 'COMPLETABLE_QUEUED_SETTLEMENT PASS ' + path + ' ' + fault:
                raise ValueError('Java CompletableFuture queued settlement control did not complete')
    result = compiler.run('scheduled-periodic-source-control', 'java', '-Xmx256m', '-cp', output,
        'ScheduledPeriodicReferenceControl').strip()
    if result != expected_periodic: raise ValueError('Java periodic scheduled source differs from reference')
    if inputs != {name: digest(read_file(compiler.sdk / name)) for name in inputs}:
        raise ValueError('Java scheduled source control inputs changed')
    return {'status': 'SDK-source-controls-passed', 'referenceJdk': 'matched-stopped-and-periodic-observables', 'sourceInputs': inputs,
        'futureCancelInterrupt': interrupt_control, 'executorOwnerSettlement': executor_settlement,
        'executorInvokeInterrupt': 'matched-14-preinterrupted-and-two-blocked-JDK-cases',
        'executorAwaitTermination': 'matched-16-preinterrupted-and-two-blocked-JDK-cases',
        'futureTaskNullFailure': 'matched-JDK-null-failure-and-retained-running-result',
        'futureTaskPublicMonitor': 'JDK-and-SDK-source-controls-passed',
        'componentExecutionPerformed': False, 'actualGuestBindingsUsed': False}


def scheduled_model_control(compiler: Compiler, output: Path) -> dict:
    """Actual pinned TeaVM public/private class identities before component cost."""
    classpath, identities = locked_model_classpath(compiler, include_platform=True, include_dependency_analysis=True)
    sources = [*sorted((compiler.sdk / 'fibers/compiler/dev/latent/guest/runtime/compiler').glob('*.java')),
        *sorted((compiler.sdk / 'fibers/dev/latent/guest/runtime/concurrent').glob('*.java')),
        compiler.sdk / 'fibers/conformance/compiler/ScheduledModelControl.java',
        compiler.sdk / 'fibers/conformance/compiler/source-control/org/teavm/dependency/LambdaEmitterControlContext.java']
    sources += [compiler.sdk / ('fibers/conformance/compiler/scheduled-source-control/' + name)
        for name in ('dev/latent/generated/Bindings.java', 'dev/latent/guest/runtime/Activation.java')]
    inputs = {path.relative_to(compiler.sdk).as_posix(): digest(read_file(path)) for path in sources}
    output.mkdir()
    compiler.run('scheduled-model-compile', 'javac', '-proc:none', '--release', '25', '-cp', classpath,
        '-d', output, *sources)
    result = compiler.run('scheduled-model-control', 'java', '-Xmx256m', '-cp',
        str(output) + os.pathsep + classpath, 'dev.latent.guest.runtime.compiler.ScheduledModelControl').strip()
    if result != ('SCHEDULED_MODEL_CONTROL PASS standard-APIs;private-task-call-entry;canonical-fields-and-methods;'
                  'ordinary-constructor;no-fallback;constructed-identities=7;actual-generated-callbacks=3;models=10'):
        raise ValueError('Java scheduled model control did not complete')
    if inputs != {name: digest(read_file(compiler.sdk / name)) for name in inputs}:
        raise ValueError('Java scheduled model inputs changed')
    return {'status': 'actual-locked-classlib-model-passed', 'models': 10,
        'constructedIdentities': 7, 'actualGeneratedCallbacks': 3,
        'jarDigests': identities, 'sourceInputs': inputs,
        'portOrApplicationClassesInitialized': False, 'actualGuestBindingsUsed': False}


def shutdown_now_source_control(compiler: Compiler, output: Path) -> dict:
    """Run actual pool/future bodies; only this host control uses the old private ledger."""
    fixture = compiler.sdk / 'fibers/conformance/shutdown-now'
    ledger = compiler.sdk / 'fibers/conformance/compiler/scheduled-source-control'
    ports = sorted((compiler.sdk / 'fibers/dev/latent/guest/runtime/concurrent').glob('*.java'))
    controls = [fixture / 'Capsule.java', fixture / 'OwnerControl.java',
        ledger / 'dev/latent/generated/Bindings.java', ledger / 'dev/latent/guest/runtime/Activation.java']
    inputs = {path.relative_to(compiler.sdk).as_posix(): digest(read_file(path)) for path in (*ports, *controls)}
    output.mkdir()
    # Same ordinary application logic as the real reference/component. Only
    # these two standard API imports select the real SDK bodies for this JVM control.
    text = read_file(fixture / 'Capsule.java').decode('utf-8')
    for name in ('CompletableFuture', 'Executors'):
        original = 'import java.util.concurrent.' + name + ';'
        if text.count(original) != 1: raise ValueError('Java shutdownNow source import is ambiguous')
        text = text.replace(original, 'import dev.latent.guest.runtime.concurrent.' + name + ';')
    selected = output / 'Capsule.java'
    selected.write_bytes(text.encode('utf-8'))
    compiler.run('shutdown-now-source-compile', 'javac', '-proc:none', '--release', '25',
        '-d', output, selected, *ports, *controls[1:])
    result = compiler.run('shutdown-now-source-control', 'java', '-Xmx256m', '-cp', output,
        'dev.latent.app.OwnerControl').strip()
    if result != 'SHUTDOWN_NOW_SOURCE_OWNER PASS observables=53':
        raise ValueError('Java shutdownNow source ownership control did not complete')
    if inputs != {name: digest(read_file(compiler.sdk / name)) for name in inputs}:
        raise ValueError('Java shutdownNow control inputs changed')
    return {'status': 'SDK-source-controls-passed', 'sourceInputs': inputs, 'ownershipChecks': 53,
        'componentExecutionPerformed': False, 'actualGuestBindingsUsed': False}



def future_queue_source_control(compiler: Compiler, output: Path) -> dict:
    """Real FutureTask/pool bodies; the existing host ledger is never a guest input."""
    fixture = compiler.sdk / 'fibers/conformance/future-queue'
    ledger = compiler.sdk / 'fibers/conformance/compiler/scheduled-source-control'
    ports = sorted((compiler.sdk / 'fibers/dev/latent/guest/runtime/concurrent').glob('*.java'))
    controls = [fixture / 'Capsule.java', fixture / 'OwnerControl.java',
        ledger / 'FutureTaskMonitorOwnerControl.java', ledger / 'FutureTaskMonitorReferenceControl.java',
        ledger / 'dev/latent/generated/Bindings.java', ledger / 'dev/latent/guest/runtime/Activation.java']
    inputs = {path.relative_to(compiler.sdk).as_posix(): digest(read_file(path)) for path in (*ports, *controls)}
    output.mkdir()
    reference = output / 'reference-jdk'; reference.mkdir()
    compiler.run('future-task-monitor-reference-compile', 'javac', '-proc:none', '--release', '25',
        '-d', reference, controls[3])
    expected = 'FUTURE_TASK_MONITOR_REFERENCE PASS run;cancel;completed-get;executor;scheduled-cancel'
    result = compiler.run('future-task-monitor-reference-jdk', 'java', '-Xmx256m', '-cp', reference,
        'FutureTaskMonitorReferenceControl').strip()
    if result != expected: raise ValueError('Java FutureTask monitor reference did not complete')
    text = read_file(fixture / 'Capsule.java').decode('utf-8')
    for name in ('FutureTask', 'Executors', 'ScheduledThreadPoolExecutor'):
        original = 'import java.util.concurrent.' + name + ';'
        if text.count(original) != 1: raise ValueError('Java FutureTask source import is ambiguous')
        text = text.replace(original, 'import dev.latent.guest.runtime.concurrent.' + name + ';')
    selected = output / 'Capsule.java'; selected.write_bytes(text.encode('utf-8'))
    reference_text = read_file(controls[3]).decode('utf-8')
    for name in ('FutureTask', 'Executors', 'ScheduledThreadPoolExecutor'):
        original = 'import java.util.concurrent.' + name + ';'
        if reference_text.count(original) != 1: raise ValueError('Java FutureTask monitor reference import is ambiguous')
        reference_text = reference_text.replace(original, 'import dev.latent.guest.runtime.concurrent.' + name + ';')
    selected_reference = output / 'FutureTaskMonitorReferenceControl.java'
    selected_reference.write_bytes(reference_text.encode('utf-8'))
    compiler.run('future-queue-source-compile', 'javac', '-proc:none', '--release', '25',
        '-d', output, selected, selected_reference, *ports, controls[1], controls[2], *controls[4:])
    result = compiler.run('future-queue-source-control', 'java', '-Xmx256m', '-cp', output,
        'dev.latent.app.OwnerControl').strip()
    if result != 'FUTURE_QUEUE_OWNER PASS checks=48':
        raise ValueError('Java FutureTask queue ownership control did not complete')
    result = compiler.run('future-task-monitor-source', 'java', '-Xmx256m', '-cp', output,
        'FutureTaskMonitorReferenceControl').strip()
    if result != expected: raise ValueError('Java FutureTask monitor source differs from reference')
    result = compiler.run('future-task-monitor-owner', 'java', '-Xmx256m', '-cp', output,
        'FutureTaskMonitorOwnerControl').strip()
    if result != 'FUTURE_TASK_MONITOR_OWNER PASS managed;active-owners;scheduled;retired-under-public-monitor':
        raise ValueError('Java FutureTask monitor ownership control did not complete')
    if inputs != {name: digest(read_file(compiler.sdk / name)) for name in inputs}:
        raise ValueError('Java FutureTask queue inputs changed')
    return {'status': 'SDK-source-controls-passed', 'sourceInputs': inputs, 'ownershipChecks': 48,
        'futureMonitor': 'JDK-and-SDK-source-controls-passed',
        'componentExecutionPerformed': False, 'actualGuestBindingsUsed': False}

def recipe_inputs() -> dict[str, str]:
    from tools.java_capsule_build import RECIPE
    paths = [Path(__file__), *sorted((ROOT / "tools/java_guest").glob("*.py")),
             ROOT / "tools/java_fiber_library_inputs.py",
             ROOT / "tools/data/java-public-wineh/e782-baseline.json",
             ROOT / "tools/data/java-llvm-private-stores/supplement.json",
             ROOT / "tools/stage_runtime_wit.py", ROOT / "tools/rust_capsule_project.py",
             ROOT / "tools/build_observation.py", ROOT / "tools/build_process.py",
             ROOT / "tools/build_process_linux.py", ROOT / "tools/build_process_windows.py"]
    paths += [ROOT / name for name in RECIPE]
    # Compile-only JDK declarations are not included in the guest component.
    paths += [ROOT / 'sdk/java-guest/fibers/conformance/scheduled-library/reference' / name
              for name in ('dev/latent/generated/Bindings.java', 'dev/latent/guest/runtime/Activation.java')]
    paths += [ROOT / 'sdk/java-guest/fibers/conformance/timers/reference/dev/latent/generated/Bindings.java']
    return {path.relative_to(ROOT).as_posix(): digest(read_file(path)) for path in paths}


def prepare(output: Path, wasi_sdk: Path, *, gradle="gradle", offline_cache: Path | None = None,
            read_only_cache: Path | None = None, fixture="threads", observe_public_wineh=False,
            derived_llvm_public=False, private_scalar_llvm_public=False, _deadline=None):
    if _deadline is not None:
        if (fixture not in {'worker-libraries', 'scheduled-library', 'shutdown-now', 'future-queue'} or type(_deadline) not in (int, float)
                or not math.isfinite(_deadline) or _deadline <= time.monotonic() + 5):
            raise ValueError('Java-worker-parent-deadline')
        # Includes the existing process owner's five-second cleanup allowance.
        _deadline = min(_deadline, time.monotonic() + 1200)
    if fixture not in {"threads", "completable", "timers", "fiber-io", "worker-libraries", "scheduled-library", "shutdown-now", "future-queue"}: raise ValueError("unknown Java fiber fixture")
    if type(observe_public_wineh) is not bool or observe_public_wineh and fixture != 'threads':
        raise ValueError('WinEH observation requires only the fixed normal public fiber fixture')
    if (type(derived_llvm_public) is not bool
            or derived_llvm_public and fixture != 'threads'):
        raise ValueError('Derived LLVM requires only the fixed public fiber compiler without replay')
    if (type(private_scalar_llvm_public) is not bool
            or private_scalar_llvm_public and (fixture != 'threads' or derived_llvm_public or observe_public_wineh)):
        raise ValueError('Private scalar LLVM requires its distinct fixed public backend mode')
    if offline_cache is not None and read_only_cache is not None:
        raise ValueError("Java dependency cache selections are mutually exclusive")
    admitted, derived_deadline = None, None
    if derived_llvm_public:
        from tools.java_guest import llvm_ssa_consumer as derived
        derived_deadline = derived.deadline()
        admitted = derived.inputs.prepare(derived_deadline)
        if wasi_sdk.resolve(strict=True) != admitted.sdk:
            raise ValueError('Derived LLVM requires its fixed authenticated input root')
    if private_scalar_llvm_public:
        from tools.java_guest import llvm_private_store_consumer as private_backend
        derived_deadline = private_backend.deadline()
        admitted = private_backend.inputs.prepare(derived_deadline)
        if wasi_sdk.resolve(strict=True) != admitted.sdk:
            raise ValueError('Private scalar LLVM requires its fixed authenticated input root')
    output = fresh(output)
    common = ROOT / "sdk/java-guest/fibers/conformance"
    selected = common if fixture == "threads" else common / fixture
    # Exercise real source attribution independently of package-directory layout.
    source = output / "src/Capsule.java"
    source.parent.mkdir(parents=True)
    source.write_bytes(read_file(selected / "Capsule.java"))
    wit = output / "wit/service.wit"
    wit.parent.mkdir()
    wit.write_bytes(read_file(common / "service.wit"))
    started = time.monotonic()
    before = recipe_inputs()
    io_profile = fixture in {'fiber-io', 'worker-libraries'}
    report = {"formatVersion": 1, "profile": "teavm-activation-fibers-io-v1" if io_profile else "teavm-activation-fibers-v1", "qualification": "pending",
              "status": "running", "nodeExecution": "not-run", "sourceDigest": digest(source.read_bytes()),
              "fixture": fixture}
    report["recipeInputs"] = before
    compiler = None
    try:
        selected_compiler = Compiler
        extra = {}
        if _deadline is not None:
            extra['_deadline'] = _deadline
        if observe_public_wineh:
            from tools.java_guest.public_wineh import PublicWinEHCompiler
            selected_compiler = PublicWinEHCompiler
        if derived_llvm_public:
            selected_compiler = (derived.CopyCostWinEHDiagnosticCompiler if observe_public_wineh
                                 else derived.CopyCostPublicCompiler)
            extra['admitted'] = admitted
        if private_scalar_llvm_public:
            selected_compiler = private_backend.PrivateScalarPublicCompiler
            extra['admitted'] = admitted
        compiler = selected_compiler(output / "compiler", wasi_sdk, gradle=gradle, offline_cache=offline_cache,
                            read_only_cache=read_only_cache, timeout=1200, **extra)
        library_jars, reference_jars = (), ()
        if fixture in {'worker-libraries', 'scheduled-library'}:
            from tools import java_fiber_library_inputs
            capture_options = {'gradle': gradle}
            if _deadline is not None:
                capture_options['_deadline'] = _deadline
            library_jars, reference_jars, report['libraries'] = java_fiber_library_inputs.capture(
                output / 'library-inputs', **capture_options)
        control = output / "reference-jdk"
        control.mkdir()
        main = control / "Main.java"
        main.write_bytes(read_file(selected / "Main.java"))
        compiler.paths["javac"] = compiler.paths["java"].parent / "javac"
        reference_sources = []
        if io_profile:
            reference_sources = [compiler.sdk / 'fibers/conformance/compiler/io-reference/dev/latent/generated/Bindings.java']
            reference_sources += [compiler.sdk / ('runtime/dev/latent/guest/' + name + '.java')
                                  for name in ('Option', 'Result', 'Unsigned64', 'Unit')]
            report['referenceKind'] = 'private-runtime-wait-reference-using-JDK-threads'
        elif fixture == 'scheduled-library':
            reference_sources = [selected / 'reference' / name for name in
                ('dev/latent/generated/Bindings.java', 'dev/latent/guest/runtime/Activation.java')]
        elif fixture == 'timers':
            reference_sources = [selected / 'reference/dev/latent/generated/Bindings.java',
                                 selected / 'TimerValidationOrder.java']
        reference_options = ['-cp', os.pathsep.join(map(str, reference_jars))] if reference_jars else []
        compiler.run("reference-jdk-compile", "javac", "-proc:none", *reference_options, "-d", control, source, main, *reference_sources)
        report["reference"] = []
        modes = 8 if fixture == 'scheduled-library' else 4
        for iteration in range(1 if fixture in {'scheduled-library', 'shutdown-now', 'future-queue'} else 3):
            reference_classpath = os.pathsep.join(map(str, (control, *reference_jars)))
            result = compiler.run(f"reference-jdk-{iteration}", "java", "-cp", reference_classpath, "Main")
            expected = [41, 42, 42, 42] if fixture == 'future-queue' else [42] * modes
            if result.strip() != ' '.join(map(str, expected)): raise ValueError("reference-JDK fiber observable mismatch")
            report["reference"].append({"iteration": iteration, "modes": list(range(modes)), "results": expected})
        if fixture == 'future-queue':
            report['futureQueueSource'] = future_queue_source_control(compiler, output / 'future-queue-source')
        elif fixture == 'scheduled-library':
            report['scheduledSource'] = scheduled_source_control(compiler, output / 'scheduled-source')
        else:
            report["completableSource"] = completable_source_control(compiler, output / "completable-source")
            if fixture == 'threads':
                report['scheduledSource'] = scheduled_source_control(compiler, output / 'scheduled-source')
        if fixture == 'shutdown-now':
            report['shutdownNowSource'] = shutdown_now_source_control(compiler, output / 'shutdown-now-source')
        if fixture == "timers":
            report["standardTimerSource"] = standard_timer_source_control(compiler, output / "standard-timer-source")
            report["standardTimerModel"] = standard_timer_model_control(compiler, output / "standard-timer-model")
        selection = {'fiber_io_profile': True} if io_profile else {}
        if library_jars: selection['application_classpath'] = library_jars
        component, report["record"] = compiler.compile(output / "src", wit.parent,
            "tests:caller/service@1.0.0", output / "build", activation_profile=True, **selection)
        if fixture in {'scheduled-library', 'future-queue'}:
            # Compiler.compile populates its private locked Gradle cache first.
            if fixture == 'scheduled-library':
                report['timerSleepAdmissionSource'] = timer_sleep_admission_source_control(
                    compiler, output / 'timer-sleep-admission-source')
            report['scheduledModel'] = scheduled_model_control(compiler, output / 'scheduled-model')
        elif fixture == 'shutdown-now':
            report['completableModel'] = completable_model_control(compiler, output / 'completable-model')
        else:
            report["throwableModel"] = throwable_model_control(compiler, output / "throwable-model")
            report["timeunitModel"] = timeunit_model_control(compiler, output / "timeunit-model")
            report["waitFrameModel"] = wait_frame_model_control(compiler, output / "wait-frame-model")
            report["completableModel"] = completable_model_control(compiler, output / "completable-model")
        if fixture in {'worker-libraries', 'scheduled-library'}:
            java_fiber_library_inputs.check(output / 'library-inputs', report['libraries'])
        compiler.check_unchanged()
        report["sdkInputs"] = {name: digest(data) for name, data in compiler.original_sdk.items()}
        report["componentDigest"] = digest(read_file(component, 64 * 1024 * 1024))
        compiler.check_unchanged()
        if derived_llvm_public:
            from tools.java_guest.llvm_ssa_consumer import retain_products
            report['derivedLlvm'] = compiler.qualification_record()
            report['derivedPublicProducts'] = retain_products(output)
            if time.monotonic() >= derived_deadline:
                raise ValueError('Derived LLVM public compiler job deadline exceeded')
        if private_scalar_llvm_public:
            report['privateScalarLlvm'] = compiler.qualification_record()
            report['derivedPublicProducts'] = private_backend.retain_products(output)
            if time.monotonic() >= derived_deadline:
                raise ValueError('Private scalar LLVM public compiler job deadline exceeded')
        if recipe_inputs() != before: raise ValueError("Java fiber qualification recipe changed during preparation")
        if _deadline is not None and time.monotonic() >= _deadline:
            raise ValueError('Java-worker-parent-deadline')
        report["commands"] = compiler.records
        (output / "compiler-inputs.json").write_bytes(compiler.compiler_inputs)
        report["status"] = "component-built-unqualified"
    except BaseException as error:
        if fixture == "threads":
            try:
                from tools.java_guest.fiber_component_inputs import retain
                retain(compiler, output)
            except BaseException:
                pass  # Failure-only retention must preserve the original compiler exception.
            if observe_public_wineh and not derived_llvm_public:
                try:
                    from tools.java_guest.public_wineh import retain as retain_wineh
                    retain_wineh(compiler, output)
                except BaseException:
                    pass  # Optional diagnostics cannot replace original failure.
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
    parser.add_argument("--fixture", choices=("threads", "completable", "timers", "fiber-io", "worker-libraries", "scheduled-library", "shutdown-now", "future-queue"), default="threads")
    parser.add_argument('--observe-public-wineh', action='store_true',
                        help='Fixed-public-only WinEH observation: historical postfailure, or explicit derived pre-Clang diagnostic only')
    parser.add_argument('--derived-llvm-public', action='store_true',
                        help='Only the fixed authenticated LLVM candidate and unchanged public compiler fixture')
    parser.add_argument('--private-scalar-llvm-public', action='store_true',
                        help='Only the independently qualified private-scalar backend and unchanged public C')
    args = parser.parse_args()
    prepare(args.output, args.wasi_sdk, gradle=args.gradle, offline_cache=args.offline_cache,
            read_only_cache=args.read_only_cache, fixture=args.fixture,
            observe_public_wineh=args.observe_public_wineh,
            derived_llvm_public=args.derived_llvm_public,
            private_scalar_llvm_public=args.private_scalar_llvm_public)


if __name__ == "__main__": main()
