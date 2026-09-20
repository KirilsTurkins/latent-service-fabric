# Catalog metadata correctness and working-set qualification

Issue #430 separates deterministic compiler correctness from the physical
working-set qualification. Both use the real `DirectoryArtifactRepository`,
`DirectoryDeploymentRepository`, publication, route compiler, persistence and
restart paths. No production resource ceiling, manifest contract, digest,
publication protocol, or routing behavior is changed.

## Assertion coverage

The ordinary fixture publishes **4 releases with 8 KiB of documentation each**.
It compiles 8 interleaved deployment IDs over those releases in one tenant, then
8 distinct tenant scopes sharing one release. The physical fixture still
publishes **32 releases with 3 MiB of documentation each (96 MiB total)**. It
compiles 32 distinct releases, then 32 scopes sharing one release. Its
publication, application and restart happen in three separate processes.

| Assertion IDs | Ordinary correctness | Physical qualification |
| --- | --- | --- |
| `persisted-metadata`, `32-releases-3-mib` | Real publication and fetched documentation contents; 4 × 8 KiB. | Original 32 × 3 MiB input, publication digest and documentation-length round trips. |
| `interleaved-grouping`, `distinct-releases`, `one-fetch-per-group` | 8 interleaved route IDs; 4 actual directory metadata fetches per apply/reopen. Existing two-digest mock regression also remains. | 32 actual directory metadata fetches per distinct-release apply/reopen. |
| `distinct-scopes` | 8 tenant scopes share one release; exactly one metadata fetch per apply/reopen. | Original 32 tenant scopes share one release; exactly one metadata fetch per apply/reopen. |
| `exact-routes-generation` | Every release and route generation checked, generation 1, exact route count; absent tenant rejected. | Every release and route generation checked, generation 1, exact route count. |
| `unchanged-restart-state` | Byte-for-byte catalog state and route snapshot unchanged by reopen. | Original byte-for-byte catalog-state restart assertion retained. |
| `512-kib-state` | Same 512 KiB catalog-state ceiling; repeated documentation absent from persisted route state. | Original 512 KiB catalog-state ceiling retained. |
| `one-owner`, `owned-documentation-bytes`, `drops-before-return` | One compiler metadata owner, at most 8 KiB of owned documentation, all owners dropped before apply/reopen returns while the resulting catalog remains live. | Not substituted for a process-memory measurement. |
| `retention-negative-control` | The same compilation intentionally retains actual metadata clones; the one-owner assertion must panic with its specific diagnostic. | Original physical fixture and threshold remain unchanged; no new, weaker physical control or threshold is substituted. |
| `three-fresh-processes`, `64-mib-physical-growth` | **Not established.** There is no RSS sampling or physical qualification claim. | Three fresh processes; original Linux `VmHWM` growth allowance of 64 MiB. |
| `complete-child-observations`, `bounded-child-lifetime-output-cleanup` | Runner/discovery tests and ordinary supervision regressions exercise failures separately. | Exact child test and phase identity, complete two-scenario measurements, successful one-test summary, bounded pipes, owned children, deadlines and private-root cleanup. |

The production compiler drops the current release metadata before awaiting the
next grouped fetch. The `cfg(test)` metadata wrapper observes the actual owned
value, including real clones and destruction. Its documentation-byte counter is
an exact observation of the fixture's interface/function documentation payload,
**not** an estimate of total heap use, allocator overhead, canonical trees, or
repository startup memory. There is no global allocator instrumentation or
production telemetry API. The session is scoped to the fixture's synchronous
polling thread, and independent tests do not share counters.

The negative control uses a test-only retainer inside the same compiler path. It
keeps cloned metadata values alive across groups and is expected to trip
`compiler metadata ownership accumulated`. It does not merely invent larger
counter values or declare a failure from the test name. The positive case must
also pass, so an unrelated publication or route failure cannot satisfy the
negative control's expected panic. The large physical test remains necessary to
catch allocation patterns outside this narrow ownership observation.

## CI ownership and discovery

`tools/ci_suites.json` is the versioned inventory consumed by the existing
`tools/ci_rust_artifacts.py` runner. It records exact libtest identities, owner,
feature recipe, classification, prerequisites, resource class, timeout, and
assertion IDs. The five previously registered fixture/integration selections
remain unchanged. This is the existing runner's libtest inventory, not a claim
that the whole-CI inventory work in #427 is complete.

`catalog-metadata-correctness` is ordinary, non-ignored correctness and includes
both the positive and negative cases. The runner checks that no selected case
has silently become ignored. `catalog-metadata-working-set` selects exactly the
original physical test with `--ignored --exact --test-threads=1 --nocapture`.
Missing, renamed, duplicate, empty, wrong-feature, or unsupported-host selections
fail; a child-only invocation cannot satisfy the parent suite.

The existing **Durable catalog acceptance** job runs both explicitly on every
`full` profile. This conservatively includes compiler, artifact/catalog,
resource-accounting, runner, and workflow changes without introducing another
path classifier. `CI result` continues requiring that job. A failure,
cancellation, unexpected skip, or missing required job cannot pass the full
aggregate. Documentation-only selection is unchanged.

Before this split, the physical test was ordinary and ran in both the workspace
all-features pass and the catalog package pass. Now those ordinary passes skip
only the ignored physical test, and the catalog job runs it **once**, using the
registered all-features recipe. Ordinary correctness still participates in
normal discovery, with a small explicit repeat for its separate timing and
negative-control observations. The default-feature catalog regressions and
workspace all-features regressions otherwise remain in place.

The 100,000-publication manual gate, profiling/calibration, Phase 0/1/2 gates and
receipt requirements are not reclassified or weakened. The metadata records
below are diagnostics, not phase receipts, authorization evidence, or cached
proof of qualification.

## Local commands

Use the pinned toolchain from [the toolchain guide](toolchain.md), a Linux host,
and a clean checkout. Commands use the repository's normal `target/` directory;
do not substitute stale inventories, foreign executables, or another target
directory. Preparing the harness is separate from executing it.

For ordinary development feedback, including the real retention negative
control, run:

```sh
cargo test -p latent-control-store --lib --all-features --locked deployments::tests::resources::compilation_memory::correctness::small_metadata_
python3 -m unittest tools.tests.test_ci_rust_artifacts tools.tests.test_catalog_metadata_suites
```

For both exactly selected suites and retained observations:

```sh
mkdir -p target/catalog-metadata
source_commit="$(git rev-parse HEAD)"
cargo test -p latent-control-store --lib --all-features --locked --no-run --message-format=json,json-render-diagnostics > target/catalog-metadata/tests.jsonl
python3 tools/ci_rust_artifacts.py --inventory target/catalog-metadata/tests.jsonl --source-commit "$source_commit" --suite catalog-metadata-correctness --record target/catalog-metadata/correctness.json
python3 tools/ci_rust_artifacts.py --inventory target/catalog-metadata/tests.jsonl --source-commit "$source_commit" --suite catalog-metadata-working-set --record target/catalog-metadata/physical.json
```

A direct `cargo test` filter can report zero matching tests on an unsupported
platform; that is **not** qualification. Use the registered runner for physical
qualification: it requires Linux and a positive, correctly formed
`/proc/self/status` `VmHWM` observation. Missing or unreadable data fails rather
than becoming a zero-byte measurement. Each physical child checks its own
measurement too. The correctness suite does not read `/proc`.

## Measurement boundaries and retained evidence

The catalog job retains `catalog-metadata-<source-sha>-<run-attempt>` for 14 days.
Its compact JSON records distinguish the selected source, recipe, host, assertion
set, successful cases and failed/not-run/cancelled executions:

* `build.json`: locked Cargo recipe, lockfile digest, verbose Rust version, host,
  workflow run/attempt, outcome and harness preparation wall time. Cache state is
  explicitly unclassified; a restored dependency cache is not a claimed cold or
  warm benchmark.
* `correctness.json`: separately timed selected execution, publication time,
  apply/reopen times for each scenario, real fetch/drop/peak-owner observations,
  state sizes, and end-to-end fixture time including teardown.
* `physical.json`: separately timed parent execution plus each fresh publish,
  apply and reopen process. Apply/reopen include per-scenario timing, baseline,
  peak and growth in KiB, state size, verified routes/generation and fetch counts.

The original physical measurement boundary is retained: directory-repository
startup precedes the baseline, and both scenarios use the process's cumulative
high-water mark. This is not an isolated allocator benchmark for each scenario,
not a claim that `max_state_bytes` bounds total process memory, and not evidence
for the separate 100,000-publication acceptance gate.

Each child has a 300-second deadline and two 64 KiB output bounds. The parent
suite has a 930-second execution deadline; listing is separately bounded. The
existing Python runner bounds aggregate output to 4 MiB and owns the process
group. Physical fixture roots are nested under a runner-owned temporary root,
removed only after group termination/reaping even on timeout or cancellation.
The Rust parent additionally owns and reaps each direct child before normal or
failure cleanup. It accepts a phase only after complete observations and an
exact successful libtest summary, never merely a zero exit status.

Use the actual records from one source/run/host when comparing costs. Build time,
fixture publication, execution, and cleanup must not be collapsed into a guessed
speedup. These commands and input sizes alone do not establish measured timing
or physical qualification; only successful observed execution does.
