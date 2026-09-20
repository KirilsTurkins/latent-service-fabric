# Prepared AOT test inputs

The `aot_supervisor`, `isolated_aot`, and `native_aot_cache` integration targets
share **immutable executable preparation**, never a catalog, lifecycle owner,
compiler authority, process owner, mutable native-cache directory, or resource
counter. Their real child-process tests remain enabled. The custom supervisor's
intentionally misbehaving worker is **not** evidence of production containment.

## Prepare, validate, execute

Use the pinned toolchain on Linux x86_64 and a clean tracked checkout. The default
recipe is debug/all-features, including opt-in parent-side timing instrumentation.
GNU `objcopy` is needed only during preparation. No extra worker is built: Cargo's
actual compiler and custom supervisor executables are copied with debug sections
removed. The cached Cargo originals are neither stripped nor replaced.

```sh
mkdir -p target
cargo test -p latent-wasmtime --all-features --locked --no-run \
  --test aot_supervisor --test isolated_aot --test native_aot_cache \
  --message-format=json > target/aot-tests.jsonl
python3 tools/aot_test_inputs.py prepare \
  --inventory target/aot-tests.jsonl --output "$PWD/target/aot-test-inputs"
python3 tools/aot_test_inputs.py validate \
  --manifest "$PWD/target/aot-test-inputs/manifest.json"
python3 tools/run_aot_tests.py \
  --manifest "$PWD/target/aot-test-inputs/manifest.json" \
  --report-dir "$PWD/target/aot-observations"
```

Preparation consumes a complete successful Cargo inventory with exact package,
target, source, profile and executable owners. It rejects duplicate or missing
roles, foreign target paths, incomplete builds and inconsistent feature sets.
The versioned, bounded manifest records the original and selected paths, sizes
and SHA-256 bytes, runtime library paths, preparation costs, and observed checkout,
lock and toolchain-file identities. It is a **same-checkout, same-job recipe**;
preparation-time checkout observations do not prove when a caller built an
inventory. The full observed build provenance and cross-job transfer contract
belong to [#428](https://github.com/KirilsTurkins/latent-service-fabric/issues/428).
This leaf recipe reuses the existing `ci_rust_artifacts` process, runtime-library
and test-list boundaries instead of adding another Cargo test framework.

An existing preparation directory is never overwritten. Validate it to reuse its
immutable inputs. After a changed checkout, lock, executable or inventory, prepare
into a new directory. Keep every original executable and its Cargo runtime
libraries available: this recipe deliberately does not support relocation or
cross-job reuse. A manifest is not an authorization credential or a native image
receipt, and no successful test result is cached.

The runner executes exact inventoried harnesses without Cargo. It verifies the
complete test listing and successful case counts; zero, missing, ignored,
filtered or duplicated cases cannot pass. It installs failing PATH sentinels for
Cargo, rustc, rustup, npm, npx, objcopy, strip, curl and wget. Its subprocess calls
are restricted to inventory-selected harnesses; validation invokes Git only.
The PATH guard detects unexpected tool use through PATH; **it is not a security
boundary and cannot prove the absence of arbitrary absolute-path subprocesses**.

Ordinary `cargo test` remains available without a prepared manifest and uses the
exact Cargo-built executable. Explicit execution-only mode, enabled by the
runner, fails with the preparation command rather than silently falling back.
The custom harness supports `--list`, `--nocapture`, and `--test-threads=1`; it is
serial and rejects unsupported filters instead of pretending to execute them.
Unsupported platforms report `NOT RUN`; the required Linux runner rejects them
before selection and never emits a successful qualification.

## Authentication and state ownership

Each test process checks the selected manifest digest and hashes both its exact
Cargo original and selected copy once for immutable **input selection**. The
existing expected-digest helper was already process-local; the optimization is
not based on claiming it hashed on every call. All subsequent production checks
remain mandatory: constructor executable verification, the actual unreaped
child's `/proc/PID/exe` verification before sending input, engine compatibility,
readiness, sandbox entry, current catalog/lifecycle checks, keyed native receipts,
framing, successful exit, and actual kill/reap ownership.

The selected copy's digest, not the original's digest, is supplied to production
configuration. The additional binary-replacement test mutates a private copy
*after* configuring the compiler. It replaces it with a still-runnable ELF with
different bytes, expects `aot-running-executable-mismatch`, checks released
resources, then successfully compiles and verifies output with a correct owner.
It never writes to a shared input. Tiny fake executables in input-parser tests
are never executed or offered as evidence of sandbox safety.

## Maintained coverage map

No parsing permutation was moved out of the real-child matrix, and no real-child
case was removed. `run_aot_tests.py` records and checks each name, not only totals.

| Target | Existing coverage retained | Additional coverage |
| --- | --- | --- |
| `aot_supervisor` | All 22 readiness/protocol/ownership scenarios: successful and malformed readiness, launch mismatch/stall, wrong approved digest, relative path, oversized/zero/truncated header/truncated body/trailing output, nonzero exit, excessive diagnostics, cancellation of a live prefix, fragmented success, running deadline, last-owner drop, active shutdown and real inherited-descriptor cleanup. Resource and actual-reap assertions stay in place. | A final unrelated real Wasmtime guest prepares and invokes successfully after all failure cases. Total: 23 named scenarios. |
| `isolated_aot` | All 9 real catalog/compiler tests, including fresh source reads, revocation, independent input budgets, compiler/engine mismatch, invalid portable bytes, output ownership, queued cancellation/deadline and shutdown. | Four tests cover missing/modified inputs, wrong digest/profile/stale identity, wrong role/symlink, and post-configuration binary replacement followed by successful real compilation. Total: 13 tests. |
| `native_aot_cache` | All 4 cold compilation/invocation, restart/reuse, exact engine, retained image/revocation, tampered bytes/unkeyed claims and wrong-host-key tests. Successful invocations, keyed receipt checks, independent catalogs, keys and image/resource counters are unchanged. | Input selection and timing only; no transition is replaced by shared cache state. |

The production `aot_sandbox` executable is unchanged and is run separately for
its maintained real Linux controls. Neither these timing observations nor the
mock supervisor worker replace the security selections owned by
[#238](https://github.com/KirilsTurkins/latent-service-fabric/issues/238) and
[PR #374](https://github.com/KirilsTurkins/latent-service-fabric/pull/374).
No guest-containment claim, production resource limit, historical receipt or
phase gate is changed.

## Reproduce the cost comparison

```sh
python3 tools/run_aot_tests.py \
  --manifest "$PWD/target/aot-test-inputs/manifest.json" \
  --report-dir "$PWD/target/aot-comparison" --compare
```

This runs the **same instrumented binaries and all 40 selected cases** first with
Cargo's original worker inputs, then with the prepared copies, then with validated
reused copies. Each case still creates fresh mutable state. Original/prepared is
an A/B measurement of the input-copy optimization on the same implementation,
not an assertion that historical CI ran the new negative tests. Preparation and
validation costs are recorded separately; building the Cargo products must also
be timed by the caller and retained alongside the report. Reuse does not rerun
objcopy, install packages, or build code.

`observations.json` includes exact executable sizes/identities, case names,
per-scenario stage records, suite wall times, preparation strip/hash costs, and
input-validation costs. Logs are bounded to 4 MiB per suite, stage events to
4096 per process, and each suite to a 600-second outer watchdog. A failure retains
a report with `passed: false`, never a successful aggregate from partial cases.
Reports are performance observations only, not production qualification receipts.

The `aot-test-timings` Cargo feature is off by default. With that feature and
`LSF_AOT_TEST_TIMINGS=1`, parent-side measurements observe the existing operations:
fixture creation/teardown, expected-digest/input validation, every mandatory
production executable hash, process launch, bootstrap/readiness, compilation plus
input/output transfer, and exit/EOF/reap. **Compilation-and-output-transfer is
parent-observed wall time, not isolated compiler CPU time**; the child environment
is still cleared, and its sandbox, protocol and diagnostic budget are untouched.
Hanging cases intentionally include their bounded wait. Nested stage totals
must not be added to suite wall time. Fixed case/stage names omit guest bytes,
authority keys, executable paths and child diagnostics.

One successful A/B/reuse sample demonstrates the measured workload, not a stable
percentage promise across machines. Compare execution savings with the complete
one-time build/preparation and repeated validation costs; moving work into a
preparation step alone is not a speedup. Retain new observations separately from
historical Phase 2/3 security evidence.
