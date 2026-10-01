# Response retention and reserved storage recovery

This implemented first retention profile uses the existing
[atomic command envelope](../../crates/latent-commit/src/atomic/mod.rs),
[protected storage owner](../../crates/latent-state/src/protected_store.rs) and
[serializable transaction contract](state-and-effects.md). It contributes the
linked response-expiry and physical recovery-capacity parts of #397.

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
purge and destructive namespace retirement require the broader declared-horizon
and audited reconciliation operations; #397 remains open for those operations.

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

Before ordinary admission opens, the host installs a finite reserve carved from
the storage owner's existing workers, queue slots, accepted jobs, response bytes
and read slots. Ordinary work cannot consume that reserve. Authorized status,
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
