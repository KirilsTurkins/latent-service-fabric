# CI Cargo recipes and dependency-cache experiment

## Status and decision

Planning/implementation baseline: `development` at
`50f003dd006e0786494936c49e55dc683cf26fd6`, pinned Rust 1.97.1 and MSRV 1.94.1.
The reviewed Cargo recipes and opt-in cache configuration are implemented.
[Issue #432](https://github.com/KirilsTurkins/latent-service-fabric/issues/432)
continues to track the measured cache/profile comparison and selection of a
faster default. Passing recipe CI does not complete those performance criteria.

**The existing dependency cache and ordinary dev/test profiles remain the
selected defaults. No compile/check invocation has been removed.** There are
no completed, equivalent end-to-end cache-service comparisons for the new
candidates yet; choosing a faster default or calling an invocation redundant
would be unsupported. The real-compiler mechanism observations below are not
a substitute for that comparison.

The ordinary CI workflow invokes reviewed recipes instead of duplicating Cargo
argument lists in shell blocks. Existing job selection, required checks,
renderer conditionals, qualification steps, artifact consumers, release builds,
and the unconditional `CI result` remain in place. The opt-in cache changes only
the Rust correctness job; it does not shard compilation into additional jobs.
Integration with the current shared suite inventory retains exact workspace
discovery, separate execution logs for ordinary tests, doctests and signing
compatibility, and authenticated AOT preparation before execution. All recipe
commands and delegated owners are registered in `tools/ci/contracts/`.

## Coverage map

`python3 tools/ci_cargo.py plan RECIPE` emits command arguments and the package,
feature, target, profile, declared toolchain, and coverage reason for each
invocation. This is configuration metadata, not an execution receipt. Host
means the selected compiler's host target; the cache candidate observes its
actual `rustc -vV` output rather than assuming an architecture.

| Recipe | Package/feature/target selection | Profile and retained purpose |
| --- | --- | --- |
| `format` | All workspace sources | Pinned rustfmt; no build profile |
| `workspace-check` | Workspace, all features, all targets, locked | Dev; feature-unified workspace checking |
| `bindings` | RPC with all features/all targets; independently selected default-feature component bindings on host and wasm32-wasip2; toolchain smoke and echo example on wasm32-wasip2 | Dev; all five independent host/guest checks |
| `production` | `latent`/`latentd` with all features but without `--all-targets`; independently selected `latent-wasmtime` AOT binary | Dev; production dependency graphs, not workspace dev-dependency unification |
| `clippy` | Workspace all features/all targets, then the existing strict four-package selection | Dev; preserve both lint policies and fail-fast ordering |
| `prepare` | Workspace/all-targets/all-features build, then the same test selection with `--no-run` and Cargo JSON output | Dev build and test build; normal binaries and exact harness inventory |
| `test` | Workspace/all-targets/all-features; admission/scheduler default-feature doctests; signing library with `ed25519-dalek/legacy_compatibility` and `crypto::tests` | Test; retain ordinary/custom harness execution, doctests and signing negative controls |
| `msrv` | Independently selected MSRV workspace/all-targets/all-features check | Dev; compiler version comes from `workspace.package.rust-version` |

All compilation/test invocations retain `--locked`. Default vectors are tested
against the pre-change workflow, including positional filters and the Clippy
`-- -D warnings` boundary. `--timings` may be added explicitly for Cargo's own
build observations; it does not turn a plan into a successful test result.

CI invokes the `workspace-tests`, `doctests` and `signing-compatibility` leaves
of `test` separately so the shared discovery validator checks each retained
execution log. These leaves reference the same command definitions as `test`;
they do not introduce separate test selections. Shell pipeline failures remain
fatal through `pipefail`.

The broad build before test preparation remains deliberate. A successful
`cargo test --no-run` alone is not evidence that it covers all build-mode units,
production feature resolution, examples, or profile-sensitive build scripts.
Cargo unit/fingerprint/timing observations must establish equivalence before
removing it or the separate checks.

Catalog acceptance, contract/SDK validators, scripted provider/renderer
preparation, WASM release builds, calibration and historical evidence collectors
keep their existing independent commands. The recipe helper never recursively
calls a repository validator and does not undo the duplicate-validation removal
from issue #183.

## Prepared artifacts are not cache evidence

`prepare --inventory PATH` removes an old inventory before building, writes new
Cargo output to a sibling temporary file, and publishes it atomically only after
Cargo exits successfully and the bounded stream has artifacts and a successful
final `build-finished` record. Failures, truncated output, duplicate keys,
post-completion records, source-file destinations and symlink destinations fail
closed. Stream-completion checks do not authenticate any executable.

The existing `tools/ci_rust_artifacts.py` and provider-specific runners remain
responsible for executable ownership, target/profile identity, expected tests
and execution. Their current `$RUNNER_TEMP/lsf-workspace-tests.jsonl` handoff is
unchanged. Neither a restored dependency cache nor this JSON stream is a passing
qualification, signing, resource or test receipt. Cargo still runs on a cache
hit, and command failure stops the recipe. There is no success-on-cache-hit path
or silent retry that can mask a failed test.

## Bounded cache alternatives

There are two dependency-cache variants, using the same pinned
`Swatinem/rust-cache@6323deb102c322ba6fcbdcafc7e3dddab59af2b6` action:

| Variant | Selection | Difference |
| --- | --- | --- |
| Baseline | Default for PR, push and manual CI | Existing prefix/key and dependency-only paths |
| Recipe identity | Manual CI input `cargo_dependency_cache=recipe` | Observed build-compatibility digest in the non-fallback prefix and a compatible shared key, without hashing workflow layout |

The baseline already requests `.fingerprint`, `build` and `deps` directories.
`cache-targets: false` is **not** evidence that compiled dependencies are absent:
those are explicit cache directories. The pinned action's save implementation
prunes workspace artifacts while retaining dependency material. The candidate
preserves `cache-workspace-crates: false`, `cache-bin: false`,
`cache-all-crates: false`, `cache-on-failure: false` and the same directory scope.
It does not cache all of `target`, workspace executables, credentials, signing
keys, fixture state, raw captures or positive/derived proof receipts. The action
also manages its ordinary dependency-download cache. The production cache does
not gain a second backend or compiler-cache service. Disposable local archives
used by the manual experiments below never read or write shared caches.

The compatibility digest includes the recipe's package/feature/target/profile
selection, root and nested manifests/locks/build scripts, toolchain declarations,
Cargo configuration (including parent/Cargo-home config, never credentials
files), actual Rust/Cargo and native-tool versions, host target/architecture,
runner image, and hashed build-affecting environment values. Values such as
`RUSTFLAGS`, encoded flags, profile overrides and native compiler flags invalidate
it; arbitrary environment dumps and credential values are not retained. Normal
source changes still let Cargo's own unit fingerprints decide what must rebuild.
Unrelated workflow layout and Markdown changes are not candidate key inputs.

The **entire** compatibility digest is in `prefix-key`, not only `key`:
rust-cache restore-prefix fallback must not drop the profile/toolchain/recipe
compatibility boundary. The candidate fails explicitly for compiler/wrapper,
linker or target-directory overrides that it does not observe, missing input
files, malformed Cargo configuration, unresolved tools and input bounds. It
currently supports the pinned native runner setup, not arbitrary custom SDKs.

Only a push to `development`, or an explicit manual run on `development` or
`release`, may save either cache. Pull requests and feature-branch manual runs
are read-only. A cache identity failure fails the selected candidate step.
A restore miss can rebuild normally. A corrupt restored dependency may be rebuilt
by Cargo or cause a nonzero Cargo result; the latter remains a CI failure. The
real-compiler mechanism trial now observes both outcomes: an invalid fingerprint
rebuilds and a damaged dependency library produces Cargo exit 101. The local
archive control rejects a damaged digest before extracting anything. These are
not GitHub cache-service corruption trials or proof of full-suite equivalence.

## Opt-in correctness profile

`.cargo/ci-correctness.toml` is not automatically read as repository Cargo config
and is not selected by normal CI. It changes only dev/test settings: debug level
1, no incremental compilation, optimization level 0, debug assertions and
overflow checks retained, and two concurrent Cargo build jobs. Cargo jobs bound
compiler/linker processes, not every internal worker thread or total RSS.
There is no release-profile override and no benchmark, calibration or historical
evidence profile change. The helper rejects applying it to the MSRV recipe.

Run it only in a separate correctness-experiment checkout; do not reuse that
checkout's `target/debug` output as ordinary qualification or resource evidence:

```sh
python3 tools/ci_cargo.py plan prepare --configuration ci-correctness
python3 tools/ci_cargo.py run workspace-check --configuration ci-correctness --timings
python3 tools/ci_cargo.py run bindings --configuration ci-correctness --timings
python3 tools/ci_cargo.py run production --configuration ci-correctness --timings
python3 tools/ci_cargo.py run clippy --configuration ci-correctness --timings
python3 tools/ci_cargo.py run prepare --configuration ci-correctness --timings \
  --inventory target/ci-experiment/workspace-tests.jsonl
python3 tools/ci_cargo.py run test --configuration ci-correctness --timings
python3 tools/ci_cargo_cache.py --configuration ci-correctness
```

Use fail-fast shell execution when automating this sequence. These commands are
only its correctness build/test portion, not a replacement for the required
integration suite. The separate profile gets a different cache identity even
though Cargo's on-disk directory is still named `debug`.

## Measurement and promotion requirements

Use the shared stage evidence from
[#426](https://github.com/KirilsTurkins/latent-service-fabric/issues/426), the
selected-suite inventory from
[#427](https://github.com/KirilsTurkins/latent-service-fabric/issues/427), and the
prepared-artifact identities/runtime wiring from
[#428](https://github.com/KirilsTurkins/latent-service-fabric/issues/428).
This change does not introduce competing stage-receipt or positive artifact
identity schemas. Coordinate compatible cache reuse and lane layout with
[#431](https://github.com/KirilsTurkins/latent-service-fabric/issues/431).

For each candidate, pin the source revision, runner image/hardware class,
toolchains, selected cases and resource concurrency. Complete one cold and at
least two repeated warm executions of the **same entire declared affected
suite**. Use trusted cache writers for warm trials; repeating a read-only PR
cannot populate an absent cache. Use disposable runner/checkouts for cold trials,
not deletion of shared contributor caches. Record:

- Every stage result, selected-case parity, critical-path elapsed time, job
  elapsed time and summed runner time, including late integration consumers.
- Cache hit/miss/fallback, downloaded/uploaded bytes, restore/transfer/extraction
  and save time, archive size, actual Cargo fresh/compiled units and build/link
  timing, including cache-key observation overhead and uncached guest units.
- Peak memory where available, identifying whether it is sampled job memory,
  process-tree memory or a child-process maximum. A missing measurement is
  unavailable, never zero; distinct peak definitions are not interchangeable.

Retain full Cargo fingerprint/timing diagnostics outside dependency caches and
reference them from the shared evidence. Compare separate process invocations
as separate Cargo unit graphs. Do not infer duplication from duration alone or
sum overlapping process peaks. Account for any cross-lane artifact transfer and
cold compilation rather than moving that cost out of the reported interval.

| Configuration | Cold | Warm 1 / warm 2 | Complete-suite parity | Decision |
| --- | --- | --- | --- | --- |
| Existing cache / ordinary profiles | Not collected for this comparison | Not collected | Not measured | Retain existing default; no speed claim |
| Recipe cache / ordinary profiles | Not collected | Not collected | Not measured | Opt-in only |
| Recipe cache / correctness config | Not collected | Not collected | Not measured | Local opt-in only; no qualification reuse |

The comparison currently has **zero samples per configuration**. Its uncertainty
is not quantified; no speedup estimate or confidence interval is claimed.

No failed, cancelled, incomplete or differently selected run is eligible as a
favorable sample. A cache hit with no successful downstream validation is not a
performance win. Preserve negative and inconclusive observations as well as
improvements. Promote a default or remove an invocation only after that evidence
shows equivalent completed coverage and a net benefit including cache overhead.
The retained mechanism corruption/mismatch trials do not establish the complete
affected-CI/cache-service comparison. Python mocks in the regression tests do
not satisfy those performance criteria either.

## Actual observations and manual replay

The manual-only `Cargo recipe evaluation` workflow installs the repository's
existing pinned Rust/MSRV/Python versions. It has read-only repository
permissions and no cache restore/save action. It is not a required PR build lane
and does not split or duplicate compilation in normal CI.

`tools/ci_cargo_observe.py` runs the existing immutable recipe vectors through
`TestRun` and the shared descendant-process owner. It records source/attempt
identity, Cargo JSON artifact freshness, hashed before/after fingerprint files,
Cargo timing HTML, bounded redacted logs, GNU time wall/CPU time and maximum
child RSS. Fresh/compiled **artifact records are not rustc invocation counts**.
Maximum child RSS is not simultaneous process-tree or job peak memory. Missing
GNU time data remains unavailable, never zero. Diagnostic export failures cannot
replace an already-observed failed Cargo exit status. A failed observer removes
its inventory handoff, and no retained observation is an artifact qualification.

```sh
python3 tools/ci_cargo_observe.py workspace-check --output "$RUNNER_TEMP/cargo-observations"
python3 tools/ci_cargo_probe.py --include-msrv --output "$RUNNER_TEMP/cargo-probe"
```

Output directories must be new; source-tree destinations, traversals and links
are rejected. The raw stream is bounded to 16 MiB, fingerprint observations to
20,000 files/16 MiB, and each JSON line to 1 MiB. These bounds fail explicitly,
not by truncating a successful sample. Evidence stays outside dependency caches.

### Retained real-compiler mechanism control

[Run 36546155736](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/36546155736),
commit `4d65364ec0217f1224879b2c2a67331283142ac1`, completed on September 29, 2026.
All 60 recipe/cache/observer tests passed on native Linux, without native-test
skips. Artifact `11022761400` has ZIP SHA-256
`a204ccd8a3d5932574b65dfac0f268a928de75f3cc1704e55866f724496fad18`.
The retained [mechanism report](evidence/cargo-cache-mechanism-2026-09-29.json)
is copied from its `probe/probe.json`, not generated from mocks.

The fixture contains one application and one dependency with exactly three
executed tests. Each configuration has one cold and two restored dependency-warm
observations on the same runner. Application outputs are pruned before saving;
every warm invocation rebuilds the application and executes all three tests.

| Configuration | Cargo elapsed cold / warm 1 / warm 2 | Built / fresh artifact records cold; each warm | Local archive bytes | Maximum child RSS KiB cold / warm 1 / warm 2 |
| --- | --- | --- | --- | --- |
| Current | 0.23 / 0.11 / 0.11 s | 2 / 0; 1 / 1 | 3,668 | 237,012 / 237,508 / 237,012 |
| Correctness | 0.15 / 0.10 / 0.11 s | 2 / 0; 1 / 1 | 3,649 | 234,976 / 236,864 / 235,024 |

Current local archive save took 0.00329 s and restores 0.00268 / 0.00260 s;
correctness save took 0.00245 s and restores 0.00254 / 0.00256 s. Pruning cost
0.05561 / 0.05642 s respectively. Stage-owner totals in the JSON are separate
from Cargo wall time; the first current stage includes first-use setup overhead.
The report does not hide that cost by labeling it compiler time.

All nine controls completed with the required outcome: a corrupt fingerprint
rebuilt both artifact records; a corrupt dependency product failed explicitly
with exit 101; a corrupt local archive was rejected before extraction; changed
flags, features, target, toolchain and dependency each built new artifacts; an
absent cache built and executed successfully. The target-change control is an
explicit wasm check, not a claim that wasm tests executed. Expected corruption
failures are mechanism outcomes, never successful performance samples.

These tiny sequential trials have only one cold/two warm samples per profile,
10 ms Cargo timer resolution, no randomized ordering and no network transfer.
They establish invalidation/failure behavior, not a statistically supported LSF
speedup. No confidence interval, default promotion or redundant-command removal
is justified by them.

### Warm archive repair on current development

[Evaluation run 36547560769](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/36547560769)
failed in both full-recipe configurations after the cold Rust suites passed.
The first warm restore rejected `unsafe-dependency-archive-member`: Cargo had
created hardlinked regular products, and Python's tar writer encoded subsequent
paths as hardlink members. The retained cold results do not count as completed
cold/warm comparisons.

Archive creation now snapshots each regular product's bytes with dereferencing
explicitly enabled. Restore still rejects hardlink and symlink members, unsafe
paths, collisions, invalid digests and all original count/byte-limit breaches.
Native Linux controls verify that two hardlinked products restore as independent
regular files and that a supplied hardlink archive is rejected before extraction.
The evaluation workflow installs the MSRV declared by current development
(1.95.0 at integration), and the command registrations use the current modular
contracts while preserving the immutable v1 inventory and existing test guards.
This repair changes no ordinary CI cache default or selected build recipe.

### Actual Rust recipe replay

Enable `run_full_recipes` in the manual workflow to replay both configurations
on separate disposable runners. For a fresh disposable checkout with **no
existing `target` directory**, the equivalent local command is:

```sh
python3 tools/ci_cargo_evaluate.py --disposable-checkout \
  --configuration current --output /absolute/path/outside-the-checkout/cargo-evaluation
```

The runner executes every entry in `RUST_RECIPES`, including deterministic helper
checks, host/guest checks, production packages, both Clippy policies, preparation,
workspace tests, explicit doctests and signing compatibility, cold and twice
warm. It compares exact discovered case identities, recreates and authenticates
AOT inputs after every preparation, and invokes the existing custom/doctest/
signing execution validators. It never equates shared artifact hashes with
redundant coverage. The former target must not exist, diagnostics must live
outside the checkout, and only the target newly owned by this invocation is
reset. Archives are bounded to 16 GiB/100,000 regular files, checked for traversal,
links, duplicates, workspace products and integrity before extraction.

The output includes per-invocation observations, exact case-identity digests,
complete selected-suite wall time, discovery/AOT preparation, local prune/save/
restore costs and bytes. Partial, failed or differently selected samples remain
failed in `evaluation.json`. Local dependency archive timings are **not** GitHub
cache download/upload timings. Downstream renderer/provider qualification,
MSRV, release and calibration jobs are explicitly excluded from this local
recipe measurement and remain in normal CI. Consequently this runner cannot
promote a default on its own or replace the shared #426/#342 end-to-end evidence.

## Rollback

Select `cargo_dependency_cache=baseline` (or omit the manual input) to return to
the existing cache without changing build/test selection. Stop passing
`--configuration ci-correctness` and use a separate clean ordinary-profile
checkout before collecting qualification evidence. No release setting, product
state or evidence schema requires migration.

To roll back the recipe refactor itself, revert this change's commit; the
pre-change Cargo commands and baseline cache declarations are restored together.
Do not restore an old namespace across incompatible recipe/profile changes or
remove the independent checks while rolling back. A future compatibility change
must update its represented inputs or namespace, never broaden restore fallback.
Do not delete unrelated shared caches to force an experimental cold run.

## Fast regression checks

```sh
python3 -m pip install --requirement tools/requirements.lock
python3 -m unittest tools.tests.test_ci_cargo tools.tests.test_ci_cargo_cache \
  tools.tests.test_ci_cargo_observe tools.tests.test_ci_cargo_evaluate
```

These regression tests require no Rust compiler. Existing foundation validators
use the pinned Python dependencies. They validate argument
and coverage retention, failure and inventory handoff behavior, compatibility
invalidation, secret exclusion, candidate configuration limits and the existing
workflow's writer/scope/default invariants. They also run in the existing docs
job and repository-contract test discovery. Native process tests are required on
CI Linux; an unsupported local environment reports a skip, not passing native
coverage. Real compilation/fault probes live in the manual-only workflow.
