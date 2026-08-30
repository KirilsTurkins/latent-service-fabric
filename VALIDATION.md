# Validation baseline

Updated on **2026-08-30** for the authorized Phase 0 executable contract, native-Linux variance calibration, profiling and resource-soak evidence, full completion receipt, toolchain baseline, Rust echo capsule fixture, and fixed generic execution-cell pool.

## Entry point

After installing the exact prerequisites in [`docs/development/toolchain.md`](docs/development/toolchain.md), a clean checkout is validated with:

```bash
python3.13 -m venv .venv
. .venv/bin/activate
python -m pip install --requirement tools/requirements.lock
make validate
```

The command is intentionally non-mutating for authoritative sources. Formatting is checked with `cargo fmt --all --check`; generated bindings, descriptors, and capsule artifacts are written below `target/` or Cargo `OUT_DIR`.

## Phase 0 completion sequence

The clean-checkout Phase 0 sequence is:

```bash
make phase0-gate
```

It runs `make validate`, repository-tool tests, the real executable spike and
containment suite, and a new full executable baseline. It then writes a
machine-readable `latent.phase0.gate.v3` receipt below `target/phase0-gate/`
after independently rebuilding the retained calibration, profile, and soak
aggregates from their raw artifacts and validating the fresh baseline against
them. A full command fails if the receipt is not `authorized`; it never reports
an incomplete or synthetic archive as a pass.

The retained [August 30 native-Linux receipt](benchmarks/phase0/receipts/native-linux-2026-08-30-b932a935/gate-summary.json)
records the fresh clean-checkout result: `pass`, `authorized`, and zero
blockers. It independently regenerates the current calibration, profile, and
soak inputs and binds them to the fresh baseline through one canonical
execution-evidence identity. Phase 1 is authorized to build on those runtime
invariants. The receipt remains explicitly non-production and non-Phase-1-API
compatible; the [August 29 receipt](benchmarks/phase0/receipts/native-linux-2026-08-29-54d02679/gate-summary.json)
is preserved as historical evidence only.

`make phase0-gate-smoke` runs the same code/contract/executable sequence with
the deterministic smoke baseline. It records the receipt for CI but does not
turn a smoke run into Phase 1 authorization; its output reports smoke
validation and authorization as separate states.

## What is validated

- The committed root `Cargo.lock` contains the selected direct dependency versions and is consumed unchanged by every Cargo command with `--locked`; CI does not generate or substitute a dependency graph. Adding Tokio to `latent-scheduler` changes only that workspace package's dependency list; existing registry checksums remain byte-for-byte unchanged.
- The pinned Rust toolchain, MSRV, target, direct dependency versions, Python requirements, and CI tool versions remain synchronized.
- Every Rust workspace target compiles, passes Clippy, and runs its tests using the committed lockfile.
- The fixed execution-cell pool tests cover startup-fixed capacity, concurrent acquisition limits, bounded FIFO rejection, duplicate activations and returns, modified and foreign lease identities, explicit cancellation, deterministic deadline expiry with an injected wall clock, queued-future drop before release, explicit and drop-triggered quarantine, unaccepted handoff reclamation, token-sequence exhaustion, and barrier-controlled multi-threaded release/cancellation and release/task-abort races.
- An integration test implements `CellPool` outside `latent-scheduler` using only the original required trait methods, mints an affine lease through `CellLease::new`, and proves that the issuer-retained `CellLeaseLifecycle` capability can disposition or observe abandonment without access to `FixedCellPool` internals.
- The runtime WIT world is staged with all platform dependencies; every platform and example WIT package is parsed by `wasm-tools`; generated Wasmtime host bindings and `wit-bindgen` guest bindings compile.
- The Rust echo guest returns normal input unchanged and its shared implementation tests cover `empty-message`, `message-too-large`, the exact 65,536-byte boundary, UTF-8 byte accounting, and bounded activation-ID logging data.
- The echo guest is built as a `wasm32-wasip2` Component Model artifact with generated WIT bindings. `wasm-tools validate` accepts it, and the extracted root world must import exactly `latent:context/context@0.1.0` and `latent:log/log@0.1.0` and export exactly `examples:echo/api@0.1.0`.
- The extracted component interface contains the exported `echo` function and both declared domain-error variants. Any ambient WASI import, missing import, or unexpected export fails validation.
- Two isolated clean echo builds must be byte-identical. A generated capsule manifest, build receipt, and SHA-256 file record stable metadata, local-build trust, the documented reproducibility boundary, and the computed component digest beneath `target/capsules/echo/`.
- All Protobuf files pass Buf lint and generate a deterministic file-descriptor set.
- All six JSON Schemas pass Draft 2020-12 meta-schema validation, and checked-in capsule, deployment, binding, policy, and trigger examples validate against their corresponding schemas.
- Rust, Go, TypeScript, Java, .NET, and C SDK interface surfaces compile or pass syntax checks.
- SDK compiler identities are verified before compilation, including Eclipse Temurin 21.0.11+10 and Zig 0.16.0 with its Clang 21.1.0 frontend targeting `x86_64-linux-gnu`; the runner-provided C compiler is not used.
- Generated directories are excluded from repository traversal without excluding malformed authoritative source files.
- Deterministic test IDs, manual time, temporary workspaces, and a current-thread future executor are covered by Rust unit tests.
- The Phase 0 gate receipt rejects omitted, duplicate, unexpected, or failed baseline checks; missing required terminal scenarios; a dirty executable shutdown/topology result; malformed, unsafe, incomplete, or altered raw archives; unverified calibration/profile measurements; weakened optimization guardrails; free-form optimization decisions; stale execution evidence; and incomplete resource evidence represented as an authorization.

## Echo fixture commands

Build and validate one generated fixture:

```bash
make echo-capsule
```

Run the two-build digest stability check explicitly:

```bash
make echo-capsule-reproducibility
```

The artifact remains generated rather than checked in. The generated `capsule.json` starts from the checked-in contract example but replaces its placeholder digest with the actual `sha256:` content digest and marks the artifact as an unsigned local clean build.

## Fixed cell-pool command

Run the focused scheduler test target explicitly:

```bash
cargo test -p latent-scheduler --all-targets --locked
```

The pool itself creates no runtime, operating-system thread, listener, socket, connection, component instance, store, or memory. Queued acquisition and deadline timers execute on the caller-provided shared Tokio runtime.

## Native-Linux Phase 0 calibration

The deterministic smoke profile and normal validation suite protect correctness.
The native-Linux calibration is a heavier explicit benchmark command and is not
part of normal shared CI:

~~~bash
tools/run_phase0_calibration.sh \
  --published-source-commit <reachable-commit-sha> \
  --published-source-tree <reachable-tree-sha> \
  --published-source-ref <durable-branch-or-tag> \
  /var/tmp/phase0-evidence/calibration
~~~

It runs the complete Phase 0 full profile at least seven times from one clean,
pushed source commit/tree and retains raw output outside the source tree,
invariant results, host provenance, and an aggregate report. The runner
requires a durable remote ref, verifies commit/tree reachability from that
ref, and records both the declared ref and resolved ref head. A missing
fixture, failed hard invariant, missing or unexpected invariant name, or
duplicate invariant name invalidates the calibration; it is never filtered
based on timing or resource values.

The checked-in [August 30 aggregate](benchmarks/phase0/calibration/native-linux-2026-08-30-52ac4754/aggregate.json)
is the seven-run calibration input verified by the authorized receipt. The
August 29 aggregate remains historical. Hosted CI must not treat either
package's machine-specific microbenchmark bands as a pass/fail gate. See
[docs/phase-0-baselines.md](docs/phase-0-baselines.md) for comparison and rerun
rules.

## Native-Linux Phase 0 hot-path profiling

Issue 40 provides a separate, manual evidence command for symbolized CPU and
allocation/copy profiling. It is intentionally excluded from shared CI and
requires a clean native-Linux host or VM plus the open-source `perf`,
`heaptrack`, and `heaptrack_print` utilities:

~~~bash
tools/run_phase0_hot_path_profiles.sh \
  --published-source-commit <reachable-commit-sha> \
  --published-source-tree <reachable-tree-sha> \
  --published-source-ref <durable-branch-or-tag> \
  --calibration-aggregate /var/tmp/phase0-evidence/calibration/aggregate.json \
  /var/tmp/phase0-evidence/profiling
~~~

The command refuses WSL, detected containers, unclean source, missing tools,
source-tree mismatch, a stale or malformed calibration, missing raw profile
artifacts, and failed Phase 0 hard invariants. The calibration must be a fresh
seven-or-more-run native-Linux aggregate whose sibling raw runs regenerate the
same record for the declared published commit/tree; the runner has no fallback
to the historical checked-in aggregate. It retains the exact commands, `perf.data`, symbolized `perf`
reports, Heaptrack data/reports, full baseline raw output, host context, and a
bounded worker/cell, allocator, and COW experiment matrix. Heaptrack allocation
attribution uses the leaf-nearest non-plumbing owner frame; a category with no
direct sample is reported as not observed at profiler resolution, not as a
zero-cost result. The aggregation test is deterministic and may run in CI; the
host-sensitive profile command may not. See [docs/phase-0-hot-path-profiling.md](docs/phase-0-hot-path-profiling.md)
for the evidence interpretation, adoption rule, and Phase 1 handoff.

The retained August 30
[`native-linux-2026-08-30-52ac4754`](benchmarks/phase0/profiling/native-linux-2026-08-30-52ac4754/README.md)
package is the v5 profile input verified by the authorized receipt. It covers
all eight required workloads and candidates, retains the complete invariant
proof, and makes no production or cross-machine performance claim. The August
29 package remains historical archive-regression evidence.

## Native-Linux long-running resource soak

The issue 39 resource plateau probe is also explicit heavyweight work, not a
shared CI job. It must run only after issue 40 has finalized the pre-Phase-1
configuration, from a clean native Linux host or VM and a durable source
commit/tree:

```bash
tools/run_phase0_resource_soak.sh \
  --published-source-commit <reachable-final-commit> \
  --published-source-tree <reachable-final-tree> \
  --published-source-ref <durable-branch-or-tag> \
  --final-configuration-commit <reachable-final-commit> \
  --calibration /var/tmp/phase0-evidence/calibration/aggregate.json \
  /var/tmp/phase0-evidence/soak
```

It rejects WSL, containers, unavailable process probes, fixture/toolchain
failure, dirty or mismatched source trees, missing raw batch samples, and a
pre-final/test-only invocation. It preserves at least three full raw processes,
each with 1,000 warm-ups excluded from analysis, 100,000 measured fresh-store
activations, all failure/recovery paths, and frequent real capacity/queue
saturation. Its aggregate revalidates every hard check and every batch's
logical-resource baseline, reports rolling ranges/final deltas/Theil-Sen late
slopes/peaks and explicit release/shutdown state, rejects both measured-window
and release-to-shutdown FD growth, and for new archives verifies that the final
measured FD count stays within a post-warm-up baseline while release/shutdown
return within a pre-runtime baseline. It reconciles raw process environment
against before/after host observations and applies #38's calibrated RSS band
for RSS/PSS/private material-growth triage only after CPU, memory, kernel,
virtualization, toolchain, allocator, fixture, and relevant configuration
identity—including prepared-cache enablement, Wasmtime allocator mode, and
initialized-memory COW—are proved matched. A mismatch or missing identity
blocks the comparison and authorization; it is never a reason to raise an
allowance.

The authorizing August 30 final-configuration raw result is
[`native-linux-2026-08-30-52ac4754`](benchmarks/phase0/soak/native-linux-2026-08-30-52ac4754/README.md):
three complete 100,000-activation processes from durable source commit
`52ac47542a05c0a1263f78a14c04a5c2e6b761f3` and tree
`cac3ececdbd0b5734691c30c0283fccff169a5f5`. Its raw hard invariants,
raw/host identity reconciliation, descriptor lifecycle, release/shutdown
topology, and matched-calibration late-window analysis pass. The lossless zstd
archive and its per-file manifest retain all raw process evidence without
duplicating earlier attempts. The package is evidence input, not an
authorization decision by itself; the retained full Phase 0 receipt verifies
it together with every other required input. The August 29 result remains
historical.

## CI jobs

The workflow fixes its host boundary at `ubuntu-24.04` and separates default Rust checks, the MSRV check, contract and echo-component validation, and SDK validation. The contracts job installs the pinned `wasm-tools` version before running the reproducible component build. The Issue 25 workflow runs `make phase0-gate-smoke` from a clean checkout and uploads the fresh baseline plus receipt. A failure in any job indicates that the executable interface baseline is no longer reproducible from a clean checkout.

After a successful contracts job, the workflow prints `build.json` and `sha256.txt` and uploads the generated component, capsule metadata, extracted interface, build receipt, and digest as `phase-0-echo-capsule-${GITHUB_SHA}` for 14 days. This retained artifact is reproducibility evidence for the locally trusted fixture; it is not a signed or distributable release artifact.

## Allocation boundary

Contract and capsule validation starts compiler and validator commands only. It does not start a service process, construct a Wasmtime engine or store, create an async runtime or worker pool, open a listener, lease an execution cell, or reserve capsule-owned execution state. The fixed pool stores only node-owned slot identifiers and generation counters while idle; activation and tenant identity exist only in bounded waiters and active leases.

## Scope

Passing the executable baseline establishes source consistency, guest behavior,
component-interface validity, fixed cell-pool accounting, real Wasmtime
invocation/containment, and same-boundary build reproducibility. A baseline
does not by itself authorize Phase 1: the retained August 30 full receipt also
verified conclusive calibration, profiling, and long-running resource evidence
and therefore authorized the handoff. It never
establishes production APIs, cross-platform byte identity, generic dispatch,
production security, dormant-service density, cluster behavior, or production
SLOs.
