# Metadata compilation: correctness and physical working set

This boundary addresses issue #430. It does not change production ceilings,
remove persistence or fsync, replace the 100,000-publication catalog acceptance
job, or issue any Phase 2/3 resource qualification.

## Inputs and coverage

The old physical fixture is retained as an ignored, explicitly selected test:
`deployments::tests::resources::compilation_memory::large_release_metadata_has_a_bounded_compilation_working_set`.
It publishes **32 distinct releases with 3 MiB of documentation each** (96 MiB),
then applies and reopens two catalogs in distinct fresh processes. Its growth
allowance is still **64 MiB above the process VmHWM baseline**; its route-state
bound is still strictly below **512 KiB**. Both scenarios share their mode's
baseline, exactly as before. These are regression allowances, not total-process
memory budgets. Publication, apply, and reopen never share allocator history.

The normal correctness fixture uses **four distinct releases, 16 KiB of
interface documentation each, and eight deployment IDs**. IDs interleave release
digests instead of pre-grouping them. It applies/reopens both (a) four releases in
one scope, with two deployments per release, and (b) one shared release in eight
tenant/service scopes. Both variants use the real directory artifact repository,
its verified-metadata read, and the production deployment store and persistence.

### Before/after assertion map

| Original assertion or regression risk | Normal correctness ownership | Retained physical ownership |
| --- | --- | --- |
| Each published release has the expected content digest | Four exact digest comparisons | Original 32 exact comparisons |
| Documentation survives real persistence and read-back | Four exact documentation strings, 16 KiB each | Original 32 read-backs, 3 MiB each |
| Distinct releases are not confused/deduplicated | Four digests interleaved among eight IDs, one scope | Original 32 releases, one scope |
| A shared release works in distinct scopes | One digest, eight tenant/service scopes | Original one digest, 32 scopes |
| One fetch per grouped digest despite interleaved IDs | Delegated production metadata-fetch map equals the exact digest-to-one map on apply and reopen; original two-digest `Releases` test remains | Not claimed: physical memory is the original assertion, not a fetch-count proxy |
| Route generation equals one | Exact generation on store and every resolved route, apply/reopen | Original exact assertions |
| List has exactly the expected number of deployments | Eight, plus every expected route resolves to the exact release | Original 32, plus every expected route resolves |
| State is smaller than the test's unchanged 512 KiB limit | Nonempty bounded persisted catalog | Original bound, plus nonempty observation validation |
| Reopen preserves persisted bytes | Exact `catalog.json` and entire routing snapshot equality | Original exact `catalog.json` byte equality |
| Full release documentation is not accumulated | Owning wrapper tracks live/peak documentation bytes and actual drops; exact one-release peak, zero live after compilation | Original VmHWM growth <= 64 MiB, 96 MiB source payload |
| Full scoped canonical trees are not accumulated | Owning canonical values have a one-contract documentation-byte peak and exact encode/drop count (one per release, not scope) | Original distinct-release and shared-release/scoped physical scenarios |
| The resource observation actually ran | No RSS reading or resource qualification is claimed | One completed child observation and one actually passed libtest per mode; both measured scenarios required |

The ownership counters deliberately count **owned documentation bytes**, not
allocator capacity, the total heap, or process RSS. The observation wraps the
actual verified metadata and canonical JSON value. A value moved into a retaining
collection stays charged until its actual drop. The observer is `cfg(test)` only
and scoped to the synchronous fixture executor's thread; unrelated parallel
libtests cannot contaminate the counters. No new production resource limit exists.
It does not claim to observe arbitrary uninstrumented allocations, serialized
scratch buffers, or every future compiler rewrite. Those remain reasons to retain
the full physical probe.

## Negative controls

`retained_real_metadata_and_canonical_values_fail_the_same_small_assertion`
executes two actual production applies. The test-only mutation delays destruction
of the real verified metadata or real canonical values instead of adding guessed
counter increments. The very same validator used by the positive fixture must
return the corresponding ownership-growth failure. The test also requires four
acquisitions, zero drops, and exactly 64 KiB of retained documentation.

The physical test also accepts an explicit local diagnostic mutation:
`LSF_METADATA_RETAIN=release` or `LSF_METADATA_RETAIN=canonical`. This retains the
same large real values and is expected to fail the original 64 MiB bound during
apply. **A failing build or missing observation is not successful negative-control
evidence**: inspect the failure and require the `compiler retained aggregate full
release/contract metadata` assertion. These controls have not been measured in the
preparation environment; do not record them as demonstrated until actually run.
The qualification runner rejects this variable and inherited child-mode/root
variables, including empty values, so a diagnostic or standalone child cannot
masquerade as the full suite.

## CI ownership and the #427 dependency

The existing `tools/ci_rust_artifacts.py` inventory registers
`metadata-working-set` with the exact package, library target, source, test name,
Linux support, prerequisites, a physical-exclusive resource class and a 930-second
outer timeout. It reuses Cargo's successful current-job artifact inventory and its
existing exact ignored-test discovery; it does not glob binaries or introduce a
second classifier. The normal workspace invocation skips only the ignored large
parent; all small correctness, observation-validation, and existing grouping tests
remain ordinary tests.

The Rust job runs the explicit suite once for **every full CI profile**, with no
optional step condition or continue-on-error. The existing classifier selects full
for catalog/compiler/resource-accounting changes and unknown/non-documentation
paths. No classifier, `CI result` aggregation, branch protection, manual phase gate,
or catalog-scale job is modified. The browser/runtime setup is not needed by the
focused local commands, although the existing full Rust CI job retains its other
requirements.

At the inspected development baseline, #427's replacement suite inventory is not
implemented. This change extends the existing inventory owner rather than inventing
a competing classifier or pretending that final #427 classification is complete.
When #427 lands, carry this stable suite identity, exact selector, full-profile
requirement, timeout and resource class into its inventory. Do not narrow its
selection without the conservative transitive coverage qualification required there.

## Process and observation contract

Each of the three child processes has a 300-second deadline. Standard output and
error are drained concurrently with independent 32 KiB caps (64 KiB total), not
unbounded log files. Owned children are killed/reaped on deadline or output failure;
readers are joined. These are non-spawning libtest probe children; the outer runner
also owns its process group and bounds total output and lifetime. The parent owns
the temporary root and removes it after all modes or a failure.

`VmHWM` must be present exactly once, positive, parseable, and in `kB`. Missing
`/proc`, zero, a missing/wrong unit or a decreasing peak fails; none is replaced by
zero or a passing skip. The publication completion is printed only after all 32
read-backs. Apply/reopen completion is printed only after both scenarios pass.
The parent and runner require exact observations, not substring markers or merely
a successful exit code.

Successful physical execution prints three `LSF_METADATA_MEASUREMENT` JSON records
with schema `latent.metadata-working-set.v1`. They include exact fixture inputs,
limits, OS/architecture, parent-measured per-process `wall_ns`, and each scenario's
baseline/peak/growth, route count/generation, persisted size and restart-byte result.
CI uploads their bounded log with failure diagnostics. This is working-set test
observation, not an authorization receipt. Historical receipts are untouched.

## Focused Linux commands

Use the repository-pinned Rust toolchain on Linux with a mounted `/proc` and a real
writable filesystem. Run from the repository root without overriding Cargo's target
directory (the existing artifact runner authenticates `target/debug/deps`).

```sh
mkdir -p target/metadata-working-set
start=$(date +%s%N)
cargo test -p latent-control-store --lib --all-features --locked --no-run \
  --message-format=json,json-render-diagnostics \
  > target/metadata-working-set/build.jsonl
printf 'build_wall_ns=%s\n' "$(($(date +%s%N) - start))" \
  | tee target/metadata-working-set/build-cost.txt

# Two ordinary tests: the positive persisted fixture and its two retention controls.
cargo test -p latent-control-store --lib --all-features --locked \
  deployments::tests::resources::metadata_correctness:: \
  -- --show-output --test-threads=1 \
  | tee target/metadata-working-set/correctness.log

# Exactly one physical parent, which owns exactly three fresh children.
python3 tools/ci_rust_artifacts.py \
  --inventory target/metadata-working-set/build.jsonl \
  --source-commit "$(git rev-parse HEAD)" --suite metadata-working-set \
  | tee target/metadata-working-set/physical.log

python3 -m unittest tools.tests.test_ci_rust_artifacts tools.tests.test_metadata_working_set
```

Use `set -o pipefail` in Bash when retaining logs so `tee` cannot hide failures.
The small output uses `metadata-correctness`, includes separate publication/apply/
reopen durations and ownership counters, and never emits the physical schema.
Its timing excludes Cargo compilation; record the separate build timing above.

To check physical regression sensitivity separately, run both explicit mutations
and retain each failing log, then run qualification without the mutation:

```sh
physical=deployments::tests::resources::compilation_memory::large_release_metadata_has_a_bounded_compilation_working_set
LSF_METADATA_RETAIN=release cargo test -p latent-control-store --lib --all-features \
  --locked "$physical" -- --ignored --exact --show-output --test-threads=1
LSF_METADATA_RETAIN=canonical cargo test -p latent-control-store --lib --all-features \
  --locked "$physical" -- --ignored --exact --show-output --test-threads=1
```

## Validation status of this patch

The prepared patch's Python observation/runner tests were executed: **10 passed**.
They exercise exact selection, malformed/missing/duplicate measurements, input and
threshold substitutions, zero-test or marker-only success, unsupported platforms,
inherited child modes and actual subprocess timeout/output bounds.

**Not executed in the preparation environment:** Cargo compilation, rustfmt,
Clippy, the small Rust production-path fixture, either physical fixture/control,
and GitHub CI. Cargo/rustc were absent and container networking could not resolve
GitHub. Consequently there are no genuine Rust fixture timing or RSS results to
retain, no demonstrated physical negative-control run, and no end-to-end completion
claim. Record actual supported-host inputs and costs before closing #430.
