# Validation baseline

Updated on **2026-08-29** for the Phase 0 executable contract, native-Linux variance calibration and resource-soak harness, fail-closed completion-gate verifier, toolchain baseline, Rust echo capsule fixture, and fixed generic execution-cell pool.

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

The retained #39 calibration and soak pass for their recorded configuration,
but no authorized full receipt exists for the current execution identity. Issue
closure is not a substitute for that receipt.

`make phase0-gate-smoke` runs the same code/contract/executable sequence with
the deterministic smoke baseline. It records the receipt for CI but does not
turn a smoke run into Phase 1 authorization; its output reports smoke
validation and authorization as separate states.

| Command | Baseline | Successful exit establishes | Authorizes Phase 1? |
| --- | --- | --- | --- |
| `make phase0-gate` | full | A current full receipt is `authorized`. | Yes, and only if the receipt says `authorized`. |
| `make phase0-gate-smoke` | deterministic smoke | Deterministic validation coverage completed. | No; a `blocked` receipt can accompany a successful smoke run. |

The full gate evaluates clean-worktree status with
`git status --porcelain --untracked-files=all`. Its own output below the root
`target/` directory is ignored; other untracked files can block authorization.
Run it from an isolated clone or worktree when local build output is present.

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
- SDK compiler identities are verified before compilation, including Eclipse Temurin 21.0.11+10 and Zig 0.16.0 with its Clang 21.1.8 frontend targeting `x86_64-linux-gnu`; the runner-provided C compiler is not used.
- Generated directories are excluded from repository traversal without excluding malformed authoritative source files.
- Source-controlled SVGs are parsed as accessible, local-only XML: each requires a
  descriptive title and description, `role="img"`, a `viewBox`, and no active,
  remote, or embedded content. The shared visual standard is
  [docs/svg-style.md](docs/svg-style.md).
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
tools/run_phase0_calibration.sh benchmarks/phase0/calibration/native-linux-YYYY-MM-DD
~~~

It runs the complete Phase 0 full profile at least seven times from one clean
source tree and retains raw output, invariant results, host provenance, and an
aggregate report. When a reachable published commit is supplied, the runner
verifies that the local execution tree is byte-for-byte the same Git tree and
records both identities. A missing fixture, failed hard invariant, missing or
unexpected invariant name, or duplicate invariant name invalidates the
calibration; it is never filtered based on timing or resource values.

Phase 1 comparisons use the checked-in
[aggregate.json](benchmarks/phase0/calibration/native-linux-2026-08-28-6a64f063/aggregate.json)
and its documented per-metric advisory bands. Hosted CI must not treat those
microbenchmark bands as a pass/fail gate. See
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
  benchmarks/phase0/profiling/native-linux-YYYY-MM-DD
~~~

The command refuses WSL, detected containers, unclean source, missing tools,
source-tree mismatch, missing raw profile artifacts, and failed Phase 0 hard
invariants. It retains the exact commands, `perf.data`, symbolized `perf`
reports, Heaptrack data/reports, full baseline raw output, host context, and a
bounded worker/cell, allocator, and COW experiment matrix. Heaptrack allocation
attribution uses the leaf-nearest non-plumbing owner frame; a category with no
direct sample is reported as not observed at profiler resolution, not as a
zero-cost result. The aggregation test is deterministic and may run in CI; the
host-sensitive profile command may not. See [docs/phase-0-hot-path-profiling.md](docs/phase-0-hot-path-profiling.md)
for the evidence interpretation, adoption rule, and Phase 1 handoff.

## Native-Linux long-running resource soak

The issue 39 resource plateau probe is also explicit heavyweight work, not a
shared CI job. A replacement or revalidation run must use the final Phase 0
configuration from a clean native Linux host or VM and a durable source
commit/tree:

```bash
tools/run_phase0_resource_soak.sh \
  --published-source-commit <reachable-final-commit> \
  --published-source-tree <reachable-final-tree> \
  --final-configuration-commit <reachable-final-commit> \
  --calibration benchmarks/phase0/calibration/native-linux-2026-08-28-6a64f063/aggregate.json \
  benchmarks/phase0/soak/native-linux-YYYY-MM-DD
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
initialized-memory COW—are proved matched. A mismatch or missing identity is
inconclusive, not a reason to raise an allowance.

The retained final-configuration raw result is
[`native-linux-2026-08-28-6a64f063`](benchmarks/phase0/soak/native-linux-2026-08-28-6a64f063/README.md):
three complete 100,000-activation processes from durable source commit
`6a64f0630cee9afa080d33f376aabadac724fa72`. Its raw hard invariants,
raw/host identity reconciliation, descriptor lifecycle, release/shutdown
topology, and matched-calibration late-window analysis pass. The lossless zstd
archive and its per-file manifest retain all raw process evidence without
duplicating earlier attempts; #39 is complete for the recorded configuration.

## CI jobs

The workflow fixes its host boundary at `ubuntu-24.04` and separates default Rust checks, the MSRV check, contract and echo-component validation, and SDK validation. The contracts job installs the pinned `wasm-tools` version before running the reproducible component build. The Issue 25 workflow runs `make phase0-gate-smoke` from a clean checkout and uploads the fresh baseline plus receipt. A completed validation failure is evidence that the executable interface baseline needs investigation; a job that fails before its steps run (for example, runner or account infrastructure) is not source-validation evidence and must be rerun.

After a successful contracts job, the workflow prints `build.json` and `sha256.txt` and uploads the generated component, capsule metadata, extracted interface, build receipt, and digest as `phase-0-echo-capsule-${GITHUB_SHA}` for 14 days. This retained artifact is reproducibility evidence for the locally trusted fixture; it is not a signed or distributable release artifact.

## Allocation boundary

Contract and capsule validation starts compiler and validator commands only. It does not start a service process, construct a Wasmtime engine or store, create an async runtime or worker pool, open a listener, lease an execution cell, or reserve capsule-owned execution state. The fixed pool stores only node-owned slot identifiers and generation counters while idle; activation and tenant identity exist only in bounded waiters and active leases.

## Scope

Passing the executable baseline establishes source consistency, guest behavior,
component-interface validity, fixed cell-pool accounting, real Wasmtime
invocation/containment, and same-boundary build reproducibility. It does not
by itself authorize Phase 1: the receipt also requires verified retained
calibration, profiling, and long-running resource evidence with the current
execution identity and a matching fresh baseline. It never establishes
production APIs, cross-platform byte identity, generic dispatch, production
security, dormant-service density, cluster behavior, or production SLOs.
