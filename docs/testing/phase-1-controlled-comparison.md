# Controlled historical/current comparison

The separate paired experiment compares the unmodified historical runtime at
`52ac47542a05c0a1263f78a14c04a5c2e6b761f3` with the current production standalone
node. It measures a declared set of production changes on one observed Linux
environment. It does not replace the August 30 native calibration, rerun the
historical full invariant proof, or by itself complete Phase 1.

Both arms use the maintained Echo guest. The bootstrap verifies that its
`component.rs` and `logic.rs` sources are identical across the two revisions.
Each arm uses its own ABI-compatible Component Model artifact; both exact
components and release executables are retained. The old CLI is an actual
historical binary, not the current compatibility facade.

The fixed semantic input and output are the 25 UTF-8 bytes
`phase0 targeted warm echo`. Both arms grant ten billion fuel, 16 MiB memory,
1000 ms wall time and 16384 log bytes, with two cells and three queue slots.
Each process prepares one component once, then executes a contiguous sequential
population. Full mode collects seven independent pairs with 40 leading warmup
calls and 400 measured calls per arm. Smoke mode uses one pair with two warmup
and four measured calls and always remains incomplete. Order alternates between
control first and candidate first. No observed timing determines selection, and
no outlier is removed.

The deliberate treatment includes typed versus dynamic dispatch, the guest ABI,
routing, admission, context, log handling and resource accounting. The historical
binary has two runtime workers; the current node has two invocation workers and
one control worker. The historical cache allows one entry and the current cache
allows four, but each observed arm must retain exactly one prepared entry, with
fresh stores and no live activation owners after every call. The current arm
checks each terminal receipt against retained status and releases its preparation
before clean node shutdown. Parent receipts independently record process identity,
exit, reaping, closed output readers and removal of temporary data.

Host, kernel, CPU, cgroup/virtualization observations, allocator environment,
toolchain, target and effective release recipe must match across the paired
processes. Instantaneous load is retained and may vary. The source revisions,
executables and components are individually bound rather than falsely required
to be identical. A full run requires clean source for both arms. Dirty smoke
evidence can validate the machinery but cannot qualify the comparison.

## Collect and replay

Build the historical control with the maintained bootstrap helper, supplying
pristine historical source and a fresh external build directory. The helper
retains the build receipt, logs, release recipe, lockfile, guest sources and
staged measurement inputs. It does not change the historical checkout. Use the
pinned repository toolchain and invoke the helper with its two positional paths:

```sh
bash tools/build_phase1_historical_control.sh \
  /path/to/pristine-historical-checkout /path/to/fresh-historical-control-build
```

Run the separate smoke profile first:

```sh
python3 tools/run_phase1_paired.py --profile smoke \
  --control-source /path/to/pristine-historical-checkout \
  --control-build-dir /path/to/historical-control-build \
  --output target/phase1-paired/smoke-review
```

`--profile full` selects the fixed seven-pair population. Builds use the retained
release recipe in both profiles. The runner bounds process lifetime and output,
preserves unsuccessful attempts, and supervises process groups. Its watchdog
does not claim it can forcibly stop arbitrary started operating-system work.

Replay the original suite, then independently regenerate and validate statistics:

```sh
python3 tools/validate_phase1_paired.py --suite target/phase1-paired/run/suite.json
python3 tools/aggregate_phase1_paired.py \
  --suite target/phase1-paired/run/suite.json \
  --output target/phase1-paired/run/replayed.json
python3 tools/validate_phase1_paired.py --aggregate target/phase1-paired/run/replayed.json
```

Keep the relative directory layout when archiving. The aggregate binds its suite;
the suite binds every raw report, metadata file, source copy, executable and
parent receipt by SHA-256 and byte count. JSON schema shape validation is
additional to semantic replay. Neither rehashing a changed sample nor changing
an aggregate value can satisfy replay without preserving all cross-file
associations and fixed controls.

## Read the observations

Each metric names its control and candidate boundaries. Preparation measures the
actual preparation API after engine construction, once per process. Current
collector revisions call `prepare_from_repository` and record
`preparation_scope: repository-acquisition-including-verified-refill`, including
the checked repository refill. The historical arm still uses its original
direct-artifact preparation API. Earlier retained candidate archives keep their
original boundary and exact source; they do not acquire this new scope on replay.
The separate #100 current/current diagnostic instead warms through its first
real RPC, as described in [measurement scopes](phase-1-measurements.md).
Warm
backend setup, guest call, host calls, reclamation, classification, reusable proof
and backend total have separately retained intervals. The guest-call interval
includes automatic canonical post-return in both runtimes. Host-call time is a
subset of guest-call time. The named post-return interval measures subsequent
host accounting; it does not time canonical post-return itself.

Semantic invocation elapsed is a wider-path contrast: the historical prepared
envelope through terminal outcome and cell disposition versus the current
persistent loopback RPC through terminal receipt. It is labelled separately from
backend intervals. Startup segments have different exclusions and remain
unmatched. Historical summed cleanup, current gaps between named intervals and
legacy residuals are never summed into a fabricated comparable cleanup metric.
In particular, `backend_total_micros` excludes repository acquisition and
activation materialization; those occur before backend execution begins.

Each pair retains per-arm distributions and median/p95/p99 differences. Across
pairs, summaries use independent process representatives and report variability
and lower/equal/higher counts. A zero control produces an explicit undefined
percentage, not infinity. Seven descriptive pairs do not establish statistical
significance, a universal performance limit, or an isolated causal cost for any
one change.

Instrumentation is part of the observed experiment. The historical collector
retains a growing sample vector; the current collector streams bounded JSON.
Their probes and serialization affect spacing between calls and possible cache
or thermal state. Process RSS therefore includes different diagnostic retention
and cannot establish an isolated runtime memory saving. Current RPC, retained
status and telemetry work also differ from the historical direct runner. The
original strict Phase 0 comparison continues to report incompatible historical
inputs or environments as `not_comparable`; this paired method does not relax it.
