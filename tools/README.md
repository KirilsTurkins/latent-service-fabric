# Repository tools

`validate_repository.py` uses only the Python standard library. It validates JSON/TOML syntax, Cargo workspace membership and path dependencies, Protobuf imports, WIT package declarations, required schemas/docs, nonempty files, and the interface-only binary policy.

`run_phase0_hot_path_profiles.sh` is the manual native-Linux evidence command
for issue 40. It requires a clean, durably published source tree plus `perf`,
`heaptrack`, and `heaptrack_print`; it is deliberately not shared CI.
`aggregate_phase0_hot_path_profiles.py` validates the retained raw tool output,
baseline invariant set, experiment matrix, and issue-38 comparison context.
