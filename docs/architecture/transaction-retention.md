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
protective metadata under the existing finite admission quotas. Explicit
terminalization, dependency purge and explicit command-floor release use the
separate review below. Public management composition and bounded compaction
remain part of the broader #397 acceptance work.

## Explicit review and dependency purge

`ResultMaintenanceOwner::terminalize` advances at most one original effect with
its finite history closure. The command identity and effect's original delivery
window must have expired; an inbox requires its original host-verified horizon.
Current host policy is checked before lookup and again at durable acceptance.
An active dispatch claim, corrupt linkage, paused restore/history or uncertain
clock refuses the whole callback. Pending commands need explicit physical-owner
recovery before they can be reviewed.

The review records authenticated attribution, original command digest, policy,
operation identity, reviewed time and a further retention horizon of at most
seven days. It resides in the existing command and current attempt, bounded to
2 KiB per copy. An expired uncertain effect retains its last uncertain receipt,
history and exact original payload; terminalization does not fabricate provider
acknowledgement. Required inbox, schema/source and original version/token metadata
remain linked until the later destructive release.

`purge` needs a fresh destructive policy and the recorded retention horizon.
Each callback deletes one validated original effect/payload/history closure or
one original attempt/result/retry-index closure. Durable audit progress supports
reopen between callbacks. Physical native readers prevent the destructive writer
fence, even after their public deadline; permits are never stolen. Final purge
keeps a bounded `LCX` identity floor in the original command row. The original
key reports expired and cannot become a fresh command in that incarnation.
Explicit drained namespace release must remove this final pin before destruction
and recreation. These ports provide no guest or administrator authority by
themselves and create no store, worker, timer or background dispatcher.

`prepare_floor_release` prepares one descriptive `PreparedFloorRelease` for the
existing namespace management owner. It requires the exact namespace generation,
a retired namespace, ready history/global restore guards and drained result
reservations, effects, payload and inbox dependencies. It checks all sixteen
original attempt/result slots and bounded retry backpointers are absent. The
native writer compares the original floor, fixed quota, namespace and history
rows; a missing or malformed chain refuses release. Active or merely quiescing
namespaces retain their identity floors.

The prepared plan holds the same single maintenance step through physical
publication. Management may append its bounded operation and audit rows without
overriding cleanup expectations or mutations. `publish` uses the existing native
reader reclamation gate and the host's final current namespace-destroy policy
and actual lifecycle drain callback. The final floor releases its accounting
pin and empty quota row. Namespace incarnation stays unchanged; only the normal
explicit destruction and recreation transitions advance it. A partial cleanup
is not a completed namespace destruction. The consuming management bridge must
retain its own attributable operation receipt and uncertain-commit recovery.

New admission uses closed version-4 command metadata and a fixed 256-byte
version-2 quota row. It charges encoded command, attempt, result, inbox, payload
and retry-index keys/values plus a conservative 65-byte table/index allowance per
row; effect metadata includes its bounded future history slots. Pending result
and later review capacity are reserved in the same atomic admission/commit.
The physical engine charges the quota reservation once; each pending command
still carries an exact ownership marker. Terminal review consumes a 24 KiB
reservation in already charged rows, so it needs no seventh row at the original
six-row result/inbox boundary. Namespace ceilings further narrow the existing
finite node limits and physical file high-water protection.

`anchor_review` installs an explicitly authorized clock anchor in that fixed
quota row. Subsequent review callbacks advance the same row without increasing
its encoded size. Generation, actual namespace/global/history rows and current
policy are fenced. Boot changes require explicit re-anchoring and never extend
original business horizons. An explicitly installed original global maintenance
anchor may seed the first namespace observation; ordinary body-expiry progress
continues to use its original global cursor.

Version-3 commands and version-1 quota rows remain readable under their original
accounting. Their bytes do not prove the new review reservation, so destructive
review and new admissions into that legacy quota refuse with an unsupported
format. No implicit accounting upgrade authorizes deletion. Mixed reservation
formats, nonzero quota padding and malformed reference chains fail coherent
startup validation.

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

The startup configuration selects a finite reserve within the storage owner's
original fixed workers, queue slots, accepted jobs, response bytes and read
slots. `install_recovery_capacity` only validates that exact installed profile;
it refuses missing, changed or live configuration and cannot create capacity
after startup. Ordinary work cannot consume that reserve. Authorized status,
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

The [source-matched Linux evidence](../evidence/transaction-retention-foundation-397.json) records all 109 state and 45 commit cases and strict owner Clippy. The same native schedule first reproduced the old cumulative-clock failure, then passed the fixed source after a real database reopen. Original qualified source and failed attempts remain preserved. This evidence covers the linked retention and physical reserve foundations, while the consuming Java/HTTP qualification and the remaining #397 operations stay separate.
