# PR #797 reconciliation

Reviewed 8 October 2026 against development
`378149d56f15d009ecd0ac77d0b751dc53a50f4f`, original PR #797 head
`eecb1ca5c30a2786b28f1db33429c1c6b3ce0b1b`, and preserved snapshot #964 head
`b54abd0b8504b889a21c121939b6f0f41ec93a10`.

## Issue and snapshot disposition

[Issue #393](https://github.com/KirilsTurkins/latent-service-fabric/issues/393)
is already closed. Merged [PR #821](https://github.com/KirilsTurkins/latent-service-fabric/pull/821)
delivered its seven qualified HTTP adapter criteria in development merge
`c9ba3b8c988f8f41d383812e0184bed7824aa6cf`. The recorded 59-case HTTP result is
historical evidence at its original source; it is not transferred to this head.
The maintained contract and operator boundaries are in
[deferred HTTP delivery](../../deferred-http.md).

[Snapshot #964](https://github.com/KirilsTurkins/latent-service-fabric/pull/964)
has no additional HTTP adapter changes relative to the old PR. Its additional
Java diagnostics and preparation work retain their own Feedback 2 owners. The
[Phase 4 preservation handoff #850](https://github.com/KirilsTurkins/latent-service-fabric/pull/850)
independently records #393 as complete and closed.

The older `qualified-http-put-once-v1` PUT prototype, endpoint fixtures and
contract remain recoverable in the original PR history and #964. They are not
added beside the delivered `qualified-http-effect-v1` profile. No retained PUT
intent is translated into a POST operation, and no historical prototype receipt
qualifies the delivered profile. The original signing-reader fixes are already
in development; unrelated website, archive-size and CI changes are excluded from
this follow-up.

## Retained startup fix

Dispatcher startup previously constructed an empty native-capacity binding even
when its protected store already had a trusted global owner. A foreign owner
could consequently bind to the dispatcher before the independent store check
rejected physical work, and command admission did not inherit the store owner.

Startup now captures the exact store binding before reserving the physical
dispatcher role or starting workers. The first wakeup and command capture use
that original owner; same-owner installation remains idempotent and foreign
installation rejects immediately. Absence remains explicit and binding poison
fails closed. An unbound store that has started native work cannot gain a late
substitute; recovery reopens the retained records and installs the trusted owner
before the new native epoch.

The existing capacity cases retain all original provider-attempt, record,
budget, cancellation and physical-retirement assertions. Foreign-owner coverage
also deliberately corrupts the dispatcher projection to preserve the independent
store check. The unbound restart case proves the pending effect stays unchanged
and dispatches once after the original owner is installed on reopen.

The exact foreign-owner regression fails with the development constructor
overlaid onto these tests: `bind_native_capacity` incorrectly returns success.
The retained constructor passes the regression and the complete 128 effects and
143 state cases on Linux/ext4. Current maintained HTTP execution is validated
separately; its result is recorded in the PR description rather than replacing
the old #821 receipt.

This is a focused startup/ownership follow-up under
[issue #391](https://github.com/KirilsTurkins/latent-service-fabric/issues/391).
It closes no additional ticket. #391's remaining dispatcher, ordering, installed
startup and recovery acceptance, and Phase 4 gate #407 remain separate. Full
hosted CI must assess the pushed head; no CI wait or merge is part of this work.
