# Java capsule compiler feasibility probes

**Research only. Issue #548 is not complete. No Java guest SDK, deployable Java
capsule, or supported Java language profile is delivered by this directory.**
The existing `sdk/java-client` is an external RPC client and is not used here.

This opt-in harness makes compiler experiments inspectable without weakening the
runtime, reviving the removed TeaVM-WASI generator, or treating JVM execution as
LSF execution. The [qualification report](../../docs/development/java-guest-feasibility.md)
records the boundary, current evidence and remaining work.

## What is exercised

`FeatureProbe.java` is a compiler corpus containing strings and UTF-8 round trips,
full-width signed and unsigned-bit-pattern arithmetic, records, arrays/lists,
exceptions and `finally`. Greeting, counting and shipping-shaped operations are
local corpus functions, **not implementations of the repository's authoritative
example contracts**. `probe.wit` is an exploratory round-trip contract; there are
no Java bindings for it yet.

`CompileProbe.java` invokes TeaVM 0.15.0 at build time for its maintained `C` and
`WEBASSEMBLY_GC` targets. It is never packaged or run by a node. The C candidate
then attempts compilation of generated `all.c` with the pinned Zig WASI target.
Both candidates attempt raw componentization without stub exports, ambient
imports or a compatibility adapter. These are experiments, not known-working
recipes. A failure at this step means the raw candidate lacks the required
bridge; it does not prove that a maintained bridge cannot be implemented.

## Prerequisites

Use a **complete checkout** of the feature branch or the eventual development
revision containing it. Install the repository prerequisites using
[the toolchain guide](../../docs/development/toolchain.md). The harness reads
`tools/toolchain.toml` rather than substituting whatever is installed:

- Python 3.13, JDK `25.0.4.1+1`, and Gradle `9.1.0`;
- `wit-bindgen 0.62.0`, `wasm-tools 1.254.0`, and Zig `0.16.0` at this revision.

The Java feature corpus requires no third-party libraries. The compiler driver
resolves TeaVM tooling/classlib 0.15.0 from Maven Central. A first compiler attempt
requires network access to Maven Central. Resolved Maven coordinates and JAR
SHA-256 hashes are retained, but **transitive dependency verification/locking is
not implemented**. This is not a hermetic build or a supported distribution.
Gradle may need network access to provision its own usual dependencies; the
harness neither downloads a Gradle distribution nor provisions a JDK.

Run trusted compiler sources only. The shared bounded-process helper provides
process ownership, cancellation, time and captured-output bounds; it is **not a
hostile-build sandbox**. Gradle/compiler processes are build-time processes and
are not evidence about dormant deployment or active guest memory.

## Run harness tests

From the repository root:

```sh
python3 -m unittest discover -s research/java-capsules -p test_probe.py -v
```

Expected result at this revision: `Ran 31 tests` and `OK`. The tests cover evidence
handling, failure classification, exact version checks, source changes,
cancellation receipts and output-directory preservation. Compiler behavior is
injected in most tests; two tests exercise the real Python child-status shim.
They do not qualify TeaVM, an ABI bridge, guest capabilities or an LSF node.
These research tests are **not registered in required CI**. Their local result
must not be described as the issue's meaningful guest-conformance CI gate.

## Run a compiler attempt

Choose a new directory for every attempt. From the repository root:

```sh
python3 research/java-capsules/probe.py --output target/java-probe-attempt-001
```

The command intentionally never reports SDK success or exits zero. Its expected
summary is `Java guest: <status>; NOT QUALIFIED; evidence: <path>`.

| Exit/status | Meaning |
| --- | --- |
| `2`, `blocked` | A command actually failed or the removed generator was observed; inspect the individual command and its captured diagnostics. |
| `2`, `incomplete` | Commands did not establish a blocker, but the missing Java WIT/LSF workflow still prevents qualification. |
| `3`, `infrastructure-error` | A prerequisite, exact version, source input, launch, capture, deadline or cleanup check failed. This is not proof of compiler infeasibility. |
| interruption, `cancelled` receipt | Cancellation propagated; no successful qualification is inferred. Abrupt process termination cannot guarantee a receipt. |

Inspect the report and retained logs:

```sh
python3 -m json.tool target/java-probe-attempt-001/report.json
```

The report records checked executable identities, source hashes, command exit
codes, elapsed build-step times and produced artifacts. `nodeInvoked` and
`admissionExercised` remain false, `runtimeMeasurements` remains null, and
`canCloseIssue` remains false even when every compiler command succeeds.

The current platform WIT is staged through `tools/stage_runtime_wit.py`. Current
C bindings generated from that WIT are retained **as a reference only**, not as
Java bindings. The probe also runs `wit-bindgen teavm-java --help` solely to retain
the removed-subcommand diagnostic. There is no fallback or obsolete generator
installation. Unexpected diagnostics remain ordinary failures, not a fabricated
expected blocker.

Compiler nonzero exits preserve both streams and their digests. Each command is
bounded by the shared process owner, with a combined 4 MiB capture limit and at
most ten minutes within the overall thirty-minute attempt deadline. On overflow,
deadline or cleanup failure the shared helper discards capture; the report says
`captureDiscarded: true` rather than inventing a compiler log. These are build
limits, not guest-runtime performance measurements.

## Common failures and cleanup

A missing tool or a JDK 21 installation produces an infrastructure failure.
Install the exact pinned prerequisites before drawing conclusions about either
TeaVM candidate. Dependency-resolution failures likewise do not demonstrate a
Java language limitation. Source changes during an attempt invalidate it.

If an output directory exists, use `target/java-probe-attempt-002` rather than
reusing it. Outputs must be strict descendants of the repository's `target/`;
source directories, the `target/` root itself and symlink escapes are rejected.
Do not use an output path owned by another build.

After preserving the entire attempt directory for review, remove **only that
attempt's** directory to discard its Gradle cache, generated files and logs:

```sh
rm -rf -- target/java-probe-attempt-001
```

There is no deployed node resource to clean up: the harness never signs,
publishes, admits, deploys or invokes a capsule. Successful deployment commands
will belong in the eventual Java authoring guide only after that path exists and
has real-node evidence.
