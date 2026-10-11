# Exact-source local Documentation job for Java builder evidence

All selected run blocks of the **Documentation and SVGs** CI job passed for
`0325b746ce89f6268d3b441257715adc96c35740`, under its original five-minute
deadline. The complete controller took **201.132071 seconds**; the job owner
recorded 198.822267 seconds. The actual environment was Ubuntu 24.04.5,
Python 3.13.5, Rust 1.97.1 and Node 24.19.0, running as unprivileged UID 23001.
[The original receipt](receipt.json), [tool versions](tool-versions.txt) and
[OS observation](os-release.txt) retain the measured evidence.

The original commands ran **285 profile/contracts/cache cases**, **70 native
process/runner cases** and **14 deterministic dependency cases**: 369 registered
cases, with one existing platform skip and all remaining cases passing. The
`LSF_REQUIRE_NATIVE_PROCESS_TESTS=1` guards remained enabled. Both ownership
coverage commands, documentation validation and the original dependency setup
passed. The original `fast`-profile-only block remained unselected because the
actual [source selection](selection.json) was `full`.
[original-run-blocks.json](original-run-blocks.json) preserves the exact commands
and conditional; [the raw module output](original-run-block-2.stderr.txt)
records the individual test results. The source's tracked files stayed unchanged.

The first OS-only attempt passed the 285 cases but encountered its missing
`rustc` prerequisite in the native runner demonstration. Its original failure is
[retained separately](original-environment-failure.json); no guard or assertion
was changed to obtain the subsequent pass. The second attempt used the separately
verified tooling image
`sha256:c19db1b2bb887c214b87d05aa7f15a6d2108758fa4f2cf04d09bddce8a627502`.

The [original stream inventory](original-stream-inventory.json) anchors each
stdout/stderr identity. Empty streams use explicit lossless JSON encodings.
All raw local receipts are also preserved outside disposable worktrees.
This completes the selected Documentation job's run blocks for the recorded
source. Full Rust/MSRV, SDK, registry, runtime and hosted aggregate results remain
separate; `fullRepositoryCiPassed` and hosted upload/attestation flags stay false.
The existing signed Java builder acceptance evidence remains in
[the original C4 composition campaign](../java-composed-c4-3b7/README.md).
