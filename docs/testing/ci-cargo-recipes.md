# CI Cargo recipes and dependency-cache experiment

## Status and decision

Planning/implementation baseline: `development` at
`50f003dd006e0786494936c49e55dc683cf26fd6`, pinned Rust 1.97.1 and MSRV 1.94.1.
This is the Cargo-invocation and cache-identity portion of
[issue #432](https://github.com/KirilsTurkins/latent-service-fabric/issues/432),
not evidence that its performance acceptance criteria have passed.

**The existing dependency cache and ordinary dev/test profiles remain the
selected defaults. No compile/check invocation has been removed.** There are
no comparable cold/warm measurements for the new candidates yet; choosing a
faster default or calling an invocation redundant would be unsupported.

The ordinary CI workflow invokes reviewed recipes instead of duplicating Cargo
argument lists in shell blocks. Existing job selection, required checks,
renderer conditionals, qualification steps, artifact consumers, release builds,
and the unconditional `CI result` remain in place. The opt-in cache changes only
the Rust correctness job; it does not shard compilation into additional jobs.

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
also manages its ordinary dependency-download cache; this change does not add a
second archive implementation or compiler-cache service.

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
unit tests exercise propagation of that failure, not real archive corruption.
An actual corrupted-archive recovery/failure trial remains required before
promoting the candidate.

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
Actual corruption/mismatch trials and a complete affected CI run are also still
required; Python mocks in the regression tests do not satisfy those criteria.

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
python3 -m unittest tools.tests.test_ci_cargo tools.tests.test_ci_cargo_cache
```

These standard-library tests require no Rust compiler. They validate argument
and coverage retention, failure and inventory handoff behavior, compatibility
invalidation, secret exclusion, candidate configuration limits and the existing
workflow's writer/scope/default invariants. They also run in the existing docs
job and repository-contract test discovery; no new permanent workflow is added.
