# Repository tools

`validate_repository.py` uses only the Python standard library. It validates JSON/TOML syntax, Cargo workspace membership and path dependencies, Protobuf imports, WIT package declarations, required schemas/docs, nonempty files, and the interface-only binary policy.

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
