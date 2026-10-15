# Response retention and reserved storage recovery

The response-expiry and explicit reviewed-retention ports use the existing
[atomic command envelope](../../crates/latent-commit/src/atomic/mod.rs),
[protected storage owner](../../crates/latent-state/src/protected_store.rs) and
[serializable transaction contract](state-and-effects.md). They contribute the
linked retention and physical recovery-capacity parts of #397.

## Linked response expiry

One node-owned `ResultMaintenanceOwner` inspects one indexed command per step.
Its durable cursor, generation, clock checkpoint and reclaimed-byte counters
commit in the same engine transaction as response retirement. A restart resumes
the cursor; concurrent owners must satisfy the original progress CAS. The owner
creates no worker or timer. Each submitted physical callback reserves 8 MiB for
the page, codecs, compare-and-swap copies and bounded dependency metadata.

Eligible terminal responses become a 94-byte `LCE` protective receipt containing
the original command, attempt, outcome, response digest, expiry and retirement
time. Command and latest attempt retain their original fingerprint, source,
formats, policy, horizons, inbox identity and effect links. Result-row count
stays reserved; encoded response-byte accounting shrinks atomically. The current
namespace incarnation and all existing result/inbox/effect/payload chains must
validate before reclamation. Missing or corrupt links fail visibly.

Pending commands retain their reserved disposition capacity. Response expiry
keeps outstanding effects and payloads, terminal inbox rows and required source
metadata. An original key with such dependencies remains an existing command;
changed input conflicts. A native reader still sees its original snapshot and
prevents compaction until physical view retirement. This profile retains the
protective metadata under the existing finite admission quotas. Identity/payload
purge and destructive namespace retirement require the separate declared-horizon
and audited reconciliation operations below. Response expiry does not invoke them.

## Explicit terminalization, purge and identity floors

The same maintenance owner also implements separately host-authorized
[terminalization and purge](../../crates/latent-commit/src/atomic/retention/review.rs).
`RetentionRequest` binds the original command digest, actor, operation, policy
and retention horizon. Each physical callback advances at most one effect or
prior attempt, persisting attributable progress in the original atomic envelope.
Terminalization stops future sends without claiming provider success; original
receipts and uncertainty remain historical facts.

Purge requires the completed terminalization review, a separate current
destructive-policy check, the original provider/inbox horizon, no live claim and
physically retired native views. It cannot discard an unresolved dependency
because the application result body expired. The final protective command floor
continues to reject reuse of the original key. [Floor release](../../crates/latent-commit/src/atomic/retention/review/release.rs)
is a separate prepared operation for the namespace destruction owner: it requires
a retired namespace, exact version, drained original dependencies, current
destroy permission and its composed audit/receipt batch. Quiescing, deployment
deletion and ordinary expiry cannot release it.

These are implemented lower-level ports, not an automatic node janitor or an
assertion that every management/CLI workflow and #397 gate is complete. The
installed integration must supply current authority and the actual physical
recovery owner; a retained request or maintenance flag grants neither.

## Conservative time and current permission

The host supplies a trusted clock sample and boot identity. Ordinary steps
require the recorded boot, nonregressing monotonic and wall clocks, an elapsed
interval of at most 60 seconds, and at most one second of wall/monotonic drift
both since the prior step and cumulatively since the authorized anchor. The
146-byte maximum version-2 progress record persists that anchor through restart;
repeated small wall-only jumps cannot reset the drift tolerance. Older progress
encodings refuse explicitly rather than inventing an approved clock anchor.
Unknown continuity, boot changes, regressions, large jumps and overflow hold
reclamation. A delayed operator schedule needs an explicit new anchor.

Anchoring requires current maintenance permission, the exact prior progress
generation and host-verified clock/history continuity. It writes only progress,
restarts the bounded scan and preserves original recovery horizons. It removes
no response. Older-history restore and a new boot must use this deliberate
recovery operation before maintenance resumes. Guest or request fields supply
neither clock proof nor maintenance authority.

Permission is checked before lookup, for the selected original command, and at
the actual engine fence. Expired responses expose no business body; current
result-read policy still controls status/replay. Retirement raises the original
command/attempt clock floor, preventing a regressed clock from making a removed
body appear current. Clock holds are domain results and must remain distinct
from engine corruption or uncertain commitment in the physical-owner wrapper.

## Physical recovery reserve

Before ordinary admission opens, the host configures a finite reserve in
`StoreIoLimits.recovery`. `install_recovery_capacity` validates those immutable
limits; it cannot add workers or repartition live work. Ordinary work cannot
consume the reserved workers, queue slots, accepted jobs or retained bytes. Authorized status,
pause/reconciliation and maintenance callbacks use `with_recovery_store`; the
resource class supplies no read or mutation permission.

A reserved read can run while the ordinary queue and native writer/read owner
are saturated. Writes share the original engine writer lock. A stalled writer
remains owned; its deadline cannot prove retirement or supply a bypass. Dropping
a public waiter retains its accepted job, buffers and byte reservation until
the physical callback and result owner retire. Unreadable storage and exhausted
recovery resources produce finite failures.

The maintained engine tests cover response expiry with an unresolved effect,
inbox redelivery and changed-input conflict after reopen, current-policy
revocation, corrupt payload links, clock/boot holds, durable page restart,
overlap refusal, native snapshot pinning and saturation of the protected store.
These tests qualify this finite profile. Public node/Java/HTTP execution evidence
is supplied by the consuming runtime and application integration tickets.

The [historical Linux evidence](../evidence/transaction-retention-foundation-397.json)
records 109 state and 45 commit cases and strict owner Clippy at its recorded
source revision. The same native schedule first reproduced the old cumulative
clock failure, then passed the fixed source after a real database reopen.
Original qualified source and failed attempts remain preserved.

The [PR #796 reconciliation](https://github.com/KirilsTurkins/latent-service-fabric/blob/200c17c26b24d6bf06d8d28102362ea714c1f4eb/docs/development/phase4-handoffs/2026-10-10/pr796-reconciliation.md)
records validation after integration with current development. Its linked
dispatcher tests expire response bodies with pending, in-flight and uncertain
effects, reopen the database, and check original identity, payload authority,
redelivery eligibility and stale receipt refusal. Consuming Java/HTTP
qualification and the remaining #397 acceptance criteria remain separate.
