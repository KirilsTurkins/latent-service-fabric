# ADR-0050: Plan capacity before deleting publication history

- Status: Accepted maintenance design; committed-history deletion is pending
- Context: First Integration Feedback #642

## Decision

Keep committed publication history pinned. Expose the existing admission ledgers
through authenticated node inventory and plan maintenance from measured remaining
budgets. Retirement and revocation remove authority, not committed payloads.
Existing bounded reclamation removes only uncommitted leftovers and zero-reference
blobs. It cannot delete historical publications.

Select a future explicit, authorized deletion protocol, with a dedicated
[implementation child #662](https://github.com/KirilsTurkins/latent-service-fabric/issues/662). Until qualified, operators stop promotions before exhausting
budgets and expand a reviewed finite limit/storage profile or explicitly provision
a separate installation from currently eligible packages. No automatic TTL
collector or manual row/directory deletion is supported. Age alone establishes
neither rollback eligibility nor the absence of active readers.

## Capacity and ownership

The `publication-catalog` inventory row reads a fixed number of existing counters
under a nonblocking publication-writer fence. No filesystem scan, retained list,
extra timer or per-publication owner is created. A busy, poisoned or indeterminate
owner reports unavailable, never zero. This observation changes neither readiness
nor admission authority; each operation still checks its own resource budgets.

Report shared blob bytes, publication-link bytes, incomplete files, web control
bytes, both metadata indexes, publication/blob counts and directory recovery
exposure against their actual ceilings. Counts include pending reservations;
files per publication have a separate limit. Decimal strings use the existing
bounded metadata surface supported by the CLI and all six SDKs.

The content ledger conservatively charges each shared blob once plus every
publication link's full length. Hard links can share one physical inode. These
charges do not measure filesystem allocation, free space, inodes, RSS or backup
size. Lifecycle, audit, protected configuration and other catalogs have separate
costs. The capacity tool leaves physical allocation explicitly unmeasured.

The guide recommends planning at 80% and stopping promotions at 90% of any
reported budget, earlier when a measured candidate plus rollback/evidence and
failure-recovery reserves will not fit. These are planning thresholds, not new
runtime admission rules. Forecast only from a finite observed release sequence;
no universal growth rate is asserted.

## Maintenance alternatives

| Approach | Decision |
| --- | --- |
| Retirement as byte reclamation | Rejected: historical content pins remain. |
| Manual row/directory deletion or live copying | Rejected: breaks durable authority or yields inconsistent state. |
| Automatic per-site TTL collector | Rejected: age is not a reference or authority check. |
| Reviewed limit/storage expansion | Current option with a complete stopped backup; retains history. |
| Independent empty installation | Explicit reprovisioning option; review eligible packages, current trust/revocations, active routes and rollback targets. It creates new operation history. |
| Explicit committed-history deletion | Selected long-term protocol, requiring the safeguards below. |

Before backup or relocation, stop release jobs and management mutations, drain
requests, stop the node and confirm clean shutdown. Preserve the entire data
directory with protected configuration, credentials, trust/revocation history and
external policy files. Preserve ownership, permissions and hard links. An
interrupted copy is incomplete and must never become a startup root. Restore
the complete set using the same compatible runtime/configuration, verify exact
routes and current eligibility, then reopen traffic. Keep the original stopped
root until the restore drill passes; never share it between live owners.

For reprovisioning, retain the stopped source backup for audit and recovery.
Carry forward current trust policy and revocations, verify original signed
packages/evidence, and explicitly renew expired evidence through the normal
authority. Review every active route and retained rollback target. A new root
must not resurrect revoked authority. The replacement stays private until all
intended publications and routes are verified. After interruption, recover
original operation IDs or abandon the incomplete replacement and restore the
complete original. Do not merge their catalogs or import historical success as
current authorization. Announce and measure the maintenance downtime.

## Required deletion protocol

Authorize exact tenant/publication IDs under current administrator policy, with
explicit operation IDs, expected generation and a catalog fence. Add durable
rollback-retention pins that prevent deletion without restoring eligibility.
Refuse active deployments, triggers, rollout candidates/bases, readers and
preparations. The reference checks and commit must share their owners' authority;
a best-effort scan is insufficient.

Bound each batch to at most 32 exact publications with finite durable intent and
tombstone records. Remove authority/index visibility at a durable commit. Release
content references through the one catalog owner; refund bytes only after unlink
and parent synchronization. Keep shared blobs until the last committed pin is
removed. Bound audit/tombstone history and retain original-operation recovery;
evicted UNKNOWN is not nonexecution. Evidence, trust and audit history must not
silently disappear with payloads. Reject older readers of a changed on-disk
format before cleanup. No worker belongs to an individual publication.

## Executable evidence and limits

Actual Linux filesystem tests cover shared hard links, active preparation and
rollback pins, retirement without refunds, a finite three-publication sequence,
near-budget rejection and interrupted uncommitted maintenance/reopen. Native
static qualification records authenticated capacity after each of four signed
publications and checks retained content after retirement/revocation. Node tests
check exact integer accounting, thresholds and rejection of unavailable data.

This qualifies current inventory and safe uncommitted maintenance, not a future
deletion protocol, arbitrary backup software or cloud/network storage. The
implementation child must qualify active-route/read races, shared-blob deletion,
rollback pins, audit retention and every commit/unlink interruption point.
Coordinate with #397 without conflating business-state and publication catalogs.
