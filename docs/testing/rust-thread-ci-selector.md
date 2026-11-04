# Rust ThreadPool integration: sparse CI consumers

This follows the [development merge](rust-thread-development-integration.md).
It fixes the shared CI selector and aggregate-result checkout, not the guest,
compiler catalogue, signed policy or any resource grant.

## Reproduced failure

At `14d8109cc42c1355d764d78ccd52822bef22b0cc`, both jobs use non-cone sparse
Git checkouts. `ci_suite_inventory.load()` imports `tools/ci_suite_cases.py`,
but neither checkout includes that loader or `tools/ci/suites.cases.d/`.
The exact workflow patterns, applied to a real local Git fixture, cause both
isolated Python entry points to raise `ModuleNotFoundError` before loading
the inventory. The normal full checkout hides this missing-input dependency.

Include those two existing inputs in both sparse checkouts. Preserve every
previous path, complete selector ancestry, commands, triggering conditions,
required-job rules and fail-closed behavior. Only the corresponding structural
job contracts change. No unrelated source fingerprint is weakened to make an
unverified error message disappear.

## Regression and validation boundary

`ClassificationTests.test_workflow_sparse_checkouts_load_the_complete_suite_case_inventory`
uses the workflow's actual patterns, a fresh local Git repository and isolated
Python processes. It compares the entire effective inventory with the normal
checkout, not just successful imports. Thus an import-only repair that still
omits additive cases also fails. The result job must still reject a failed
documentation job.

Both original missing-loader subcases fail before the repair. Both subcases
also fail when only the case-fragment directory is removed from the repaired
patterns. With the complete inputs, all 23 selector tests and all five result
tests pass locally with no skips. All 22 earlier selector cases retain exactly
their existing fixture and skip guards. The expanded test contract and both
workflow job contracts match their actual source structures.

The combined selector/result/process/snapshot/capacity run executes 74 tests:
70 pass, one existing Windows-only case skips on Linux, and three full-repository
capture checks cannot complete in the partial local review export (missing Git
HEAD or workspace members). They remain mandatory and unchanged in hosted CI.
The successful focused run must not be substituted for those full-checkout
checks or reported as a fully green PR.

The historical [signed ThreadPool result](rust-thread-retirement-confirmation.md)
remains unchanged. A replay of its frozen native products is not qualification
of newly merged host sources. Broader #743/#689 requirements and final hosted
integration validation remain separate; no ticket closure or release is claimed.
