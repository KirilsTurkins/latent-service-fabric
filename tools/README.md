# Repository tools

`validate_repository.py` uses the Python standard library plus the pinned
`jsonschema` dependency. It validates JSON/TOML syntax, accessible local-only
source-controlled SVGs, Cargo workspace membership and path dependencies,
Protobuf imports, WIT package declarations, required schemas/docs, nonempty
files, and the interface-only binary policy. The visual rules for those SVGs
are in [`../docs/svg-style.md`](../docs/svg-style.md).

`run_phase0_hot_path_profiles.sh` is the manual native-Linux evidence command
for issue 40. It requires a clean source tree, a durable published branch/tag
whose reachable commit and tree are verified before execution (with an
explicitly recorded `origin`-tracking-ref fallback for offline reruns), plus `perf`,
`heaptrack`, and `heaptrack_print`; it is deliberately not shared CI.
`aggregate_phase0_hot_path_profiles.py` validates the separate full-invariant
proof, scenario-selective profile commands, quantitative folded-stack
attribution, experiment matrix, provenance, and issue-38 comparability.
`reassemble_phase0_hot_path_profile_archive.py` verifies and losslessly joins
the checked-in raw-evidence fragments for a published profile archive. Its
test reassembles the checked-in zstd stream, extracts it, and validates the
raw SHA-256 manifest.

`run_phase0_resource_soak.sh` is the manual native-Linux plateau command for
issue 39. It requires an explicit durable final source commit/tree and refuses
WSL, containers, dirty or mismatched source, unavailable probes, fixture or
toolchain failures, and incomplete process output. Its paired
`aggregate_phase0_resource_soak.py` revalidates all raw samples and hard
invariants, reconciles each process environment against before/after host
observations, and validates terminal release/shutdown topology plus the full
FD lifecycle (post-warm-up, pre-runtime, release, and shutdown baselines).
It applies calibrated late-window decisions only when CPU, memory, kernel,
virtualization, toolchain, allocator, fixture, and configuration identity—
including prepared-cache enablement, Wasmtime allocator mode, and initialized-
memory COW—are recorded as matched; otherwise the result is explicitly
inconclusive. The command is intentionally excluded from shared CI.

`run_phase0_gate.sh` is the clean-checkout Phase 0 sequence. It combines the
repository and tool tests, real executable spike/containment proof, a fresh
baseline, and `validate_phase0_gate.py`. The validator emits a
`latent.phase0.gate.v3` receipt. Before it accepts an aggregate, it validates
the raw calibration tree or zstd archive, checks every manifest entry and raw
artifact, rejects links/traversal/extra files, and regenerates the aggregate
with the existing aggregation logic. It also binds calibration, profiling, and
soak evidence to a canonical execution-relevant Git-tree identity for the
current clean checkout. Its full mode returns non-zero unless the receipt is
authorized; smoke mode records a receipt and prints its validation result and
Phase 1 authorization state separately.
