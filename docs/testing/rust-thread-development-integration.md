# Rust ThreadPool development integration

This integrates development `816b806d61c3479b3e138fa55466c22250818f07`
with the runtime/evidence checkpoint
`6eb9c0863a20a593f4be32809de5149b9b83655f`. Their common ancestor is
`26966f822eaafcfad7749836e749b3ac25c5a9e8`. The existing branch history and
[successful signed campaign](rust-thread-retirement-confirmation.md) remain intact.
This integration does not close #743 or #689 or enable the shipping builder.

## Conflict resolution

The three-way merge has three conflicting files. The compiler workflow retains
the branch's ordinary-application push selector and development's reviewed
security-fork pins. Both changes were already present together in the branch.
The native reader retains the matched `cddfb5d` compiler/native tuple, exact
`push` event, complete 200-control contract and original refusal checks.
Development's second 193-control attempt is already retained in `PREVIOUS_JOB`,
`PREVIOUS_ARTIFACT` and `PREVIOUS_RECEIPTS`; its first attempt remains historical.
The reader fingerprint is kept with that exact implementation. The existing
native-reader test additionally asserts the older attempt's job, archive and
receipt identities so neither provenance chain can disappear during resolution.

All 264 development-only changed paths are preserved byte-for-byte, including
CORS, Java GC, C preimage limits, grouped CI owner contracts and the 9,248-file
source-capture ceiling. Shared changes are reconciled rather than replaced by
one entire side. The component-threading crate still has the same 76 named
library tests; development extends existing C preimage cases rather than adding
or removing test names. No test-count expectation or resource budget is relaxed.

The signed workflow's Python setup and artifact upload now use the same reviewed
security-fork revisions as development. Repository/path, inputs, permissions,
commands, deadlines and retention are unchanged, so their existing structural
workflow contracts remain exact. Temporary merge-inspection machinery is removed
from the resulting tree.

## Validation boundary

The merge was computed from immutable Git trees. Every exported review blob was
checked against its Git object identity, and the complete tree inventories were
used to verify preservation of development-only paths. The merged CI contract
set loads without duplicate identities: 1,672 semantic fragments, 399 delegated
owners and 1,436 required command blocks. All workflow models match their
reviewed contracts; all 392 available owner files in the partial local source
export match their committed fingerprints. The remaining seven owners and full
repository checks require the hosted complete checkout.

The old successful signed run authenticates the original `cddfb5d` native
source, not this merged host. In particular development changes the shared C
preimage parser and other host inputs. Frozen receipts must not be rewritten
or relabeled as post-merge builds. The compiler programme, native producer and
complete PR checks must execute the integrated source independently. A signed
replay with historical native products remains historical-product evidence,
even when its consumer script runs on the merged branch.

The finite default-pool result remains separate from synchronization/TLS/panic,
checkpoint fairness, exhaustion, networking, cancellation and cross-tenant
qualification. The existing false qualification flags and original signed
five-call expectations are unchanged.
