# Rust dependency reconciliation

PR #979 incorporates the source updates from #980 and #981: direct wasmparser
0.261.0, SPDX parser 0.13.6 and libc 0.2.190. Wasmtime remains 48.0.5 and every
other deliberate toolchain pin stays unchanged. These dependency PRs name no
owning repository ticket and close none.

The repository's declared wasmparser pin now matches the requested direct
dependency. Cargo regenerated the standalone Rust authoring lock with exactly
the libc version/checksum update and unambiguous dependency spellings; its
unchanged drift validator checks every retained package against the workspace
lock. All 52 Linux authoring, dependency and conservative SPDX source controls
pass. The fixed SPDX 3.23 producer vocabulary and its historical provenance
remain separate from the newer runtime expression parser.

The original measurement smoke CI failed its existing required-binary guard
after Cargo built an unoptimized libtest with debug symbols. Smoke now declares
a finite symbol-free test recipe while explicitly retaining debug assertions
and overflow checks. It preserves the artifact bound, workload, process-group
cleanup, deadlines and all required cases. Full release measurement recipes and
qualification requirements remain unchanged. 43 focused runner/evidence controls
pass, including the original two Linux-only controls that still need the Linux
rerun; no full scale, soak or calibration campaign was run.

The preceding Java processor delivery and the additive floor-release SDK repair
were merged normally. Current-head hosted checks and native parser/packaging plus
actual smoke validation remain required before merge. The original failed CI
artifacts and all dependency branches remain preserved.
