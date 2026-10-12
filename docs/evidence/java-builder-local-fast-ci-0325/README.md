# Exact-source local Fast host correctness job for Java builder evidence

Both original **Fast host correctness** workflow run blocks passed for
`0325b746ce89f6268d3b441257715adc96c35740`. The complete attempt took
**386.777185 seconds**; the original job owner recorded 384.327251 seconds,
within its unchanged 20-minute deadline. The actual environment was Ubuntu
24.04.5 and Python 3.13.5 in the separately inspected immutable tooling image
`sha256:c19db1b2bb887c214b87d05aa7f15a6d2108758fa4f2cf04d09bddce8a627502`.
The original process selected the pinned Rust 1.97.1 toolchain and ran as UID
23001. Its source tracked files stayed unchanged.

The [affected receipt](affected-receipt.json) retains actual discovery and
execution of **422 active native cases across 27 registered targets**, with the
two existing historical ignored cases preserved. The [narrow receipt](narrow-receipt.json)
retains **147 active native cases across five registered targets**. Empty
compile-only targets remain empty. The native runner independently matched
registered case names, minimum counts and ignored sets, then required each
actual execution summary to equal its original discovered counts.

All original formatting, all-target/all-feature checks, configured Clippy,
admission strict Clippy, native test-build/discovery/execution and selected
Rust doc-test commands passed. The [source selection](selection.json) preserves
14 selected host packages and their 17-package workspace dependency closure.
The original narrow State fixture selected five of those 14 packages. Neither
command depended on Wasmtime, Cranelift, the renderer or the Node runtime.
The private Cargo cache was created for this attempt; no shared native build
cache was used. [Original workflow commands](original-run-blocks.json) and
[the unchanged owner receipt](receipt.json) preserve the exact programs and
conditional.

The [first controller failure](original-controller-failure.json) remains
recorded: it successfully compiled the selected targets but placed the target
directory outside the original native discovery owner's expected `source/target`.
That attempt failed before native execution. The new attempt corrected only
this controller environment path; every repository assertion, suite case and
production source stayed unchanged.

[The complete original streams](complete-original-streams.tar.gz) retain both
attempts, all compile/test output, command arguments, image inspection and
receipts, including original empty streams. The [member inventory](original-stream-inventory.json)
anchors every original byte sequence; every archive member was independently
rehashed after capture. The original uncompressed receipts remain preserved
outside disposable worktrees.

This qualifies the selected Fast job run blocks for the recorded source.
[The paired Documentation job](../java-builder-local-docs-ci-0325/README.md)
is separate evidence for that same commit. Full repository CI, other Rust/MSRV
lanes, guest SDK builds, registry/runtime qualification, hosted artifacts and
attestations remain separate; `fullRepositoryCiPassed` remains false.
The original signed Java builder acceptance campaign remains in
[the C4 composition evidence](../java-composed-c4-3b7/README.md).
