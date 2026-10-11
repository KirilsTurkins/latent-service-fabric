# PR #811 completion and cancellation reconciliation

## Issue and comment context

[PR #811](https://github.com/KirilsTurkins/latent-service-fabric/pull/811)
advances [#388](https://github.com/KirilsTurkins/latent-service-fabric/issues/388),
which owns shared guest execution, transaction completion and cancellation.
It also consumes the durable command and authorized recovery contract in
[#387](https://github.com/KirilsTurkins/latent-service-fabric/issues/387).
Neither issue closes through this PR.

Both issue bodies and all their comments were reviewed, along with the bodies
and comments on dependencies #382, #384, #385, #386, #389, #393 and #408. The
closed contract, namespace, transaction, atomic-envelope and HTTP adapter
tickets supply the existing owners. #389 retains the six-guest execution matrix;
#408 retains installed query and freshness qualification. The October 8 cleanup
comments preserve historical source and checks, while explicitly leaving #388
and #387 open for integration and installed evidence. The request to finish this
PR resumes implementation after that cleanup checkpoint.

#388 requires original sealed admission authority, budgets and deadlines, actual
guest teardown before eligible completion, rejection and cancellation semantics,
no immediate-effect bypass and no automatic guest retry. Commit acceptance must
linearize against cancellation without inventing durability. Accepted uncertain
native work retains its real owners. Lost delivery cannot erase confirmed durable
outcomes or turn a dropped observer into an abort.

## Development and snapshot reconciliation

The original PR head is `f149bb009952e823c6d6f3877af80b298c5c7258`. The normal
merge incorporates development `3c2a7ba32f19a82b12a30b1a805dbe1d93b9bc12`.
Development already integrates `NativeTransactionAdmission`, `CommandCompletion`,
`TransactionCommitControl`, the command role, protected store, current-authorized
replay, native retention and the supported accounted/legacy record formats.
The reconciled tree keeps these owners and their lifecycle contracts. The older
parallel coordinator remains recoverable in the original parent and snapshots;
its incompatible admission/completion hooks do not replace the current owner.

[#961](https://github.com/KirilsTurkins/latent-service-fabric/pull/961) preserves
source `74368f3f9ff40d0457316d75b8606c60d77744e5`, already an ancestor of the
original #811 head. It supplies no additional patch.

[#970](https://github.com/KirilsTurkins/latent-service-fabric/pull/970) preserves
the distinct continuation `b9f005b427a73b557a8ab4be003c4a6ba95acaaa`. Its
alternative coordinator adds historical result authority, original-source
metadata, explicit fenced retry and query wiring alongside a broader recovery,
effects and SDK stack. Those changes remain a separate preserved continuation;
they are not transplanted over development's current owners or treated as
installed qualification. Current original-source, namespace/history, result-read,
retry and query acceptance criteria remain with their issue owners.

[#853](https://github.com/KirilsTurkins/latent-service-fabric/pull/853) preserves
an interrupted command-deduplication integration. Delivered #787, #790 and #791
provide the current persistence, waiter and replay implementations. Restoring its
older conflict stack would replace those reconciled implementations.

## Delivered follow-up

The cancellation registry previously returned `AlreadyTerminal` with the proposed
completion state while accepted irreversible I/O was still pending. Its internal
terminal state was absent, and that same I/O could later report platform failure.
The proposal therefore was not a truthful terminal cancellation result.

Accepted commit I/O now remains a nonterminal marker. Cancellation returns
nonretryable `Unavailable` with the closed
`activation.command-commit-acceptance-observed` detail and directs recovery to
current-authorized durable lookup. It preserves the registration, accepted writer,
budget and recovery identity. Actual publication determines the terminal state;
the regression covers an eventual platform failure after proposed success.
The cancellation-versus-acceptance race retains its original winner semantics.

The journal and budgeted executor propagate this result. The journal regression
also checks that another tenant observes `NotFound`, the owning tenant receives
the pending error, and its original status remains nonterminal until publication.
Ordinary accepted, repeated, missing and terminal cancellation behavior is kept.

The useful diagnostic fix from the original branch recognizes only the exact
nonretryable permission-denied `fixture-busy` constructor. Rust and Python share
the closed reason vocabulary. Wrong codes, retry flags, extra detail fields and
private or malformed variants remain unclassified; no arbitrary message enters
the child-failure snapshot. Existing preparation, scheduler and lifecycle reasons
remain intact. The Python contract adds its new case without removing old cases
or fixture and skip guards.

## Validation and remaining acceptance

The Linux node suites pass 215 cases: 135 library, 67 activation lifecycle,
five runner, five runner-race and three scheduling-cancellation cases. The new
journal assertions also pass through the existing exact test. The Wasmtime
diagnostic suite passes all ten cases. These exercise source and native fixtures;
they do not qualify an installed signed node or the six-guest matrix.

The full Python 3.13.5 Linux suite passes 3,718 cases with the 18 existing
environment guards skipped. The focused diagnostic and CI contract/coverage
modules pass 113 cases without skips. All 51 previous Python security cases and
their existing guards are preserved; the contract adds exactly one case.

Production discovery validates all 43 registered node, Wasmtime and control-store
targets and 1,036 active cases, preserving the exact case names, selections and
ignore states. The actual control-store cancellation/expiry/drop regression also
passes. Workspace all-target/all-feature checking and Clippy pass, including the
strict latent, latentd, latent-testkit and latent-admission warnings policy.
Workspace formatting, build-foundation and documentation checks pass. CI coverage
retains 88 baseline and 280 current required run blocks and 148 delegated owners.

#388 remains open for installed standalone/direct/RPC/HTTP command, cancellation,
crash/restart and real guest execution evidence, including the mandatory six-guest
matrix owned with #389 and Java #718. #387 retains complete installed deduplication,
recovery, current/delegated result-read and retention evidence. Neither source
fixtures nor historical green checks satisfy those remaining criteria.

Hosted CI is not awaited after push. This delivery does not merge the PR, close a
ticket or reattribute historical receipts to the new source.
