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
qualification requirements remain unchanged. All 95 combined Linux source
controls pass without skips, including both original process ownership controls.
Native packaging/parser 78, audit 48 and Wasmtime 354 tests pass; the two existing
explicit measurement ignores remain. The maintained real smoke runner completes
scale, soak and benchmark cases on a clean source tree with all clean shutdown
reports. Its actual 212953848-byte libtest has no debug symbols and retains debug
assertions and overflow checks. [Exact source and bounded receipt identities](../../../testing/evidence/rust-dependency-smoke-control-2026-10-13.json)
preserve this evidence. No full scale, soak or calibration campaign was run.

The preceding Java processor delivery and the additive floor-release SDK repair
were merged normally. The subsequent .NET protobuf receipt repair changes only
two client metadata hashes; these native receipts retain their actual earlier
source identity. Current-head hosted checks remain required before merge. The original failed CI
artifacts and all dependency branches remain preserved.
