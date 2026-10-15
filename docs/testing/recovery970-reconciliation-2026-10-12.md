# Restored-effect close source reconciliation

This reconciles [snapshot #970](https://github.com/KirilsTurkins/latent-service-fabric/pull/970),
original `fd8853fd0e51235d17661079720faf4c810cd6bb`, with the current delivered
foundation `e650d9c9023fefb64cdbb17a223ea9fda1cdc0a4`. The original authored
`dd4951b1` delta contains 27 files; that is not a test count or ticket acceptance
receipt. Subsequent accepted integration identities and actual execution are
recorded in the accompanying source-bound receipt.

The initial merge exposed 325 conflicts across older and current foundations.
Original index stages, index bytes, working/staged patches and feature sources
were preserved privately before resolution. The original checkpoint and its
integration history remain recoverable on preservation refs. The subsequent
history reconciliation rebuilt the intended tree on accepted development;
the old history is retained at
[`054a0dd7`](https://github.com/KirilsTurkins/latent-service-fabric/tree/preserve/pr970-before-history-reconcile-20261013).
Historical receipts retain the source IDs they actually tested. No competing
older node/store/transaction runtime is restored.

## Distinct behavior retained on current owners

| Boundary | Reconciled implementation |
| --- | --- |
| Effect v3 | [EffectRecord](../../crates/latent-effects/src/dispatch.rs) uses a distinct `LER` v3 envelope containing the original record and exact close-receipt digest. Original v1/v2 shapes remain closed and reject marker/null/header smuggling. Existing record-format identity reports version 3 for closed records. |
| Explicit close | [Recovery close](../../crates/latent-effects/src/recovery_close.rs) inspects actual paused restored rows and prepares one bounded atomic close-without-redrive operation. Scope, actor, operation, acknowledgement, clock, namespace/view/guard and original row/payload/history/due identities stay fenced. Stable effect IDs and retained payload/history remain unchanged. |
| Original accounting | The same tenant update and atomic persistence boundary charge the one immutable receipt. Receipt replay has no mutations and does not recharge or advance the original tenant counter. Exhausted metadata fails before changing retained work. |
| Linked closure | Dispatch validation, startup, census and retention validate each v3 receipt and its exact payload/history/original-record links. Generic reclamation refuses this shared receipt format rather than orphaning a linked decision. No acknowledgement, retry or remote rollback is inferred. |
| Existing v1 offline owner | [Finite retained reconciliation](../../crates/latent-state/src/recovery/v1/offline/retained.rs) runs on the original exclusive ProtectedStoreOwner/fixed workers. Requests/replies are at most 16 KiB, row/expectation limits remain 256, and original scratch charges precede acceptance. Business/result/inbox/guard mutations are forbidden; restore review remains paused. Default codecs expose no mutable port or authority. |
| Restore authority | Original `f0929671` write/publication fences are adapted under v1. The installed owner rechecks current authority before destination creation, at row writes and publication/engine-close/unlock boundaries. The default denies. Late loss preserves commit uncertainty and never manufactures rollback. |
| Protected file limits | Original `4ead362c` operator file ceilings narrow the native snapshot limit at startup/open/read/write/checkpoint. Zero/oversized limits reject; no operator input can widen the original ceiling or gain recovery authority. |

The [v1 profile](../../crates/latent-state/src/recovery/v1.rs) remains explicit.
It refuses protected v2 tenant/migration/resume formats; old bytes are never
relabelled as current protected snapshots. The current state bootstrap, native
capacity, namespace ownership, installed transaction path and stateless behavior
remain the delivered owners.

## Original boundary and current gateway continuation

The original [authenticated gateway](https://github.com/KirilsTurkins/latent-service-fabric/blob/fd8853fd0e51235d17661079720faf4c810cd6bb/apps/latentd/src/standalone/state/recovery/mod.rs),
[current-authority close action](https://github.com/KirilsTurkins/latent-service-fabric/blob/fd8853fd0e51235d17661079720faf4c810cd6bb/apps/latentd/src/standalone/state/recovery/reconciliation.rs)
and original decoder/catalog/request graph remain recoverable at the exact
checkpoint. Their absence from current source does not prove safe supersession.

The initial reconciled source checkpoint retained startup diagnosis and the
lower-level controls while identifying the missing installed gateway. The
[current gateway continuation](recovery970-current-gateway-2026-10-12.md) now
wraps current signed installation, tenant accounting, protected checkpoint,
physical Fresh restore and purpose-specific authorization owners. It retains
the old byte approval boundary and adds separate current proposal inspection.
The [2026-10-15 progress packet](evidence/recovery970-current-progress-2026-10-15.json)
records separate native build and collector identities: EARLY HTTP passes,
ordinary terminal and pending recovery fail at protected-store startup, and
the hosted publication browser observes a required `503` response. These
failures remain unresolved. The complete signed/operator campaign remains
unqualified; the earlier native receipt below retains its original source.

The [2026-10-14 clean-source progress packet](evidence/recovery970-current-progress-2026-10-14.json)
records 1,958 passing active controls, 66 preserved ignores, three real guest
controls and six native tools on exact source `6a380a5990b0`. Its separate early
HTTP programme passed. The complete terminal programme failed at pre-host stale
conflict abort persistence, and the pending restore/close programme failed at a
nested publication/policy fence during original resume. All four individual
post-stage fault cases passed, including measured native memory exhaustion and
its original durable abort. Those individual results do not qualify either
failed complete programme or transfer to later source changes.

The [clean signed early HTTP receipt](evidence/java-early-http-clean-source-2026-10-13.json)
records source `7c4a0dcc`, compiler source `47e4e607`, and six separately frozen
native tools. Five actual HTTP exchanges prove typed immediate denial,
byte-identical duplicate and retained-result replay, unchanged business state,
zero TCP contact and physical retirement of four node sessions. The protected
clock concurrency regression failed on the original source and passed after
sampling and publication were serialized. This qualifies the separate early
fixture on that source only; terminal recovery, pending restore/close, original post-stage
rollback and packaged distribution acceptance remain unqualified.

Earlier early-fixture zero-root failure observations queried the ordinary
service. They cannot establish rejection before activation acceptance. The
observer now explicitly records and queries the selected campaign service;
the original failed attempts remain preserved with their original bytes.

## Actual controlled workload and acceptance limits

The adapted [HTTP recovery schedule](../../crates/latent-http/src/deferred/tests/recovery.rs)
uses the current HttpEffectAdapter, broker/provider credentials, bounded TLS peer,
protected logical snapshot stream, fresh owned restore root and current dispatcher.
One native common state/command/intent envelope commits before backup. The real
peer applies its effect after backup and loses the reply. Restoring the older
snapshot produces Pending work and paused review; explicit close/replay and
review/resume keep the stable effect terminal, with one remote mutation and one
POST. Actual store/dispatcher/pool/socket retirement is asserted.

Its installed codecs and application association are synthetic native fixtures,
not a signed/admitted language component or a released operator workflow. Setup
and compiler failures stay recorded: the old fixture's dummy schema is refused,
the real schema must also match admission, startup needs its actual checkpoint,
and the remote receipt uses the maintained endpoint key. Those failures were
resolved at their fixture/API boundaries without relaxing product validation.

The original 138 effect, 356 state and 60 HTTP library cases remain registered.
The current inventory adds 12 close, six retained/fence/file-bound and one actual
HTTP recovery case. Inventory discovery is separate from execution; exact passing
counts, source/lock/compiler/executable identities and limitations belong to the
execution receipt. A 105-case scope was not established and is not asserted.

The [fresh native receipt](evidence/recovery970-native-reconciliation-2026-10-12.json)
also binds accepted Main `fec1092b`, including the delivered Rust and outbound
reconciliations. All 150 effect, 362 state and 61 HTTP cases pass on that source
with no failures or ignored cases. Formatting, documentation, repository and CI
coverage checks pass. Scoped Clippy passes under the maintained repository lint
policy; additional stricter probes retain baseline warnings rather than changing
that policy or presenting them as clean warnings-as-errors execution.

[#399](https://github.com/KirilsTurkins/latent-service-fabric/issues/399) still
requires complete backup/payload/format/clock/result-access and installed paused
restore qualification. [#388](https://github.com/KirilsTurkins/latent-service-fabric/issues/388)
still requires the installed shared transaction path and all six guest results.
[#391](https://github.com/KirilsTurkins/latent-service-fabric/issues/391) retains
ordering, retained-format/old-revision and installed lifecycle gates.
[#709](https://github.com/KirilsTurkins/latent-service-fabric/issues/709) retains
its authenticated diagnostic programme and actual Java/profile requirements.
These bodies and their stopped-work comments were read; no issue closes from
this source reconciliation, native subset, CI or merge.

Sensitive snapshot rows and credentials remain only in private owned fixture
directories. Public delivery contains maintained source and compact receipts,
never application backup payloads, signing secrets or an implied restore grant.
