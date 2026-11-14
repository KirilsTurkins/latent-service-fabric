# TypeScript runtime stack continuation

## Scope

Continuation of PR #1852 and stacked PRs #1931 / #1934 on 2026-11-11.
Source was restored from the exact parent `c480be742b070220a6aee27ebd2d8f9b6d57ce22`,
ownership `c34ff183a039dab3fd6aadbf9693135a0d5c1ac6`, and engine
`de25926b54b6d909fa69656d9bc5879ffca66b9e` trees. Raw blob hashes and full tree
identities were checked, not inferred from filenames or an older archive.

## Shared CI blockers corrected

The historical-source inventory must include both the new frozen Rust-thread
producer and the still-used C/ordinary-worker producer. The actual workflow
already fetched both: the test omitted the latter after their identities split.
The corrected assertion continues to reject duplicate or unrelated revisions.

The C once and timed workflows now select `tools/c_guest/closed_headers.py`,
which is already part of their authenticated build recipes. Their reviewed
workflow contracts include the same path. The minimal C-thread comparison still
requires exactly the same paths and unchanged bytes outside `src/main.c`; it no
longer substitutes a stale total file count for those stronger comparisons.

The Go deadline reference now recognizes the current immediate readiness path:
zero timeout belongs only to direction 2, while ordinary read/write still takes
the minimum of the original activation/idle deadline and the requested timeout.
Mutation controls reject removal of that direction guard, observation boundary,
or original/minimum deadline. These are source/reference controls, not live
provider qualification. No runtime limits, grants or success predicates changed.

## Executed local validation

The five failures recorded in CI run 43052513613 were reproduced, corrected,
and rerun successfully. The engine branch's maintained ownership selection ran
81 tests successfully under GCC and under Clang ASan/UBSan with leak detection
and halt-on-error enabled. These counts record runs; they are not required counts.
The broader C/Go selection also encountered an unavailable historical Git object
in the offline workspace, so it is not reported as a complete pass.

## Remaining qualification boundaries

Existing Store teardown-panic retention is already present in #1931; it is not
reimplemented here. Withholding reuse and retaining owners after a destructor
panic do not establish successful operating-system decommit or retryable cleanup.
Failed decommit custody and complete original-budget byte attribution still need
implementation and evidence. Linked SpiderMonkey collection and final combined
signed-component execution must be established independently; finite doubles
and sanitizer controls are not that evidence. No issue is closed or API support
promoted by this continuation.
