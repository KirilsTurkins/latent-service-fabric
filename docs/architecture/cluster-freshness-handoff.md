# Route freshness: Phase 5 implementation handoff

[RFC-0004](../../rfcs/0004-route-and-authorization-freshness.md) and
[ADR-0030](../../adr/0030-bound-disconnected-authorization-validity.md) complete
Phase 3's design ticket #274. This page assigns the required Phase 5 implementation
and executable evidence. **The distributed scenarios below have not been
implemented or run by this documentation change.**

The current [standalone publication boundary](../reference/publication-runtime.md)
remains the comparison baseline. Local lifecycle/admission fences determine
whether exact routed, queued or prepared work may start. They do not contact or
learn revocations from a remote controller.

## Implementation responsibilities

| Phase 5 owner | Required delivery before clustered authorization is supported |
| --- | --- |
| Control-plane desired state and durable storage (`latent-control`) | Serialize current checkpoint/lease issuance with revocation, persist authority epochs/sequences and exact publication associations, define consistent full checkpoints and contiguous deltas. A standby cannot issue from stale state. |
| Distribution protocol and authenticated node transport (`latent-wire` / cluster adapter) | Versioned bounded route envelopes/leases, authenticated cluster/catalog/node/boot audience, explicit publication and delegation fields, finite decode/verification work and fail-closed old-reader behavior. |
| Node route and authority installation (`latentd`, `latent-control-store`, `latent-routing`) | Atomic installation under the local start fence, durable replay floors before exposure, bounded staging, no permission from incomplete updates, deterministic reconnect and denial when retention cannot safely compact. |
| Lifecycle/trust/capability authorities (`latent-artifacts`, `latent-policy`, Phase 3 broker) | Exact independent publication generations/evidence/grants, revocation invalidation, explicit preservation of unchanged bindings, current provider and descendant checks. Never inherit permission from component/native-code sharing. |
| Supported cluster platform/isolation profile | Trusted time interval, monotonic drift and suspend/restart behavior, fresh boot challenge, protected floors and recovery procedure. Unsupported clocks/hosts reject the profile. |
| Activation and remote invocation (`latent-activation`, executor/transport adapters) | Recheck queued/ready work at guarded start; preserve exact pins and original deadlines, conserve descendant budgets, retain owners through real cleanup, reject stale remote pins without substitution. |
| Shared control workers and observability | Finite watch/renewal/reconciliation queues, bytes/timers/leases/floors; no dormant-service worker. Tenant-scoped expiry/outage/currentness diagnostics with redacted bounded evidence. |
| Phase 5 release gate and operator runbook | Reproducible multi-process fault matrix below, upgrade/recovery instructions, selected platform limits, configured numeric bounds and measured worst observed denial/cutover times with their limitations. |

Phase 5 planning must create implementation tickets for these owners before
starting cluster work and link them to this accepted contract. This handoff does
not move the cluster implementation into the Phase 3 completion gate (#240).
Phase 3 integrated security work (#238) keeps testing the existing local fences;
it must not label those results distributed-revocation evidence.

## Scenario and conformance matrix

Use controllable clocks and fault injection for boundary tests, then a bounded
real controller/two-node setup for disconnect, persistence and cutover evidence.
Keep node B and publication B independent where the scenario targets A. Test
both default bounds and stricter negotiated limits; equality at expiry denies.

| Scenario | Required observation |
| --- | --- |
| Connected, unchanged route and current authority | Normal invocation resolves locally; its trace contains no synchronous control-plane request. It records the exact publication/revision/checkpoint used at start. |
| Partition before remote revoke | Previously authorized A may start only before the earliest lease/disconnection/route/evidence deadline. Remote revoke is not falsely described as immediately visible. No start occurs at/after the conservative deadline. |
| Local install of revoke before partition | Routed, queued and ready A cannot start. A cached route, prepared/native hit, duplicate lease and reconnect replay cannot restore permission. |
| Revoke races with lease issuance at controller | Serialization produces either a prior finite lease or denial; no fresh lease based on pre-revoke state is issued after the revoke commit. Include a stale standby. |
| Revoke races with guarded start at node | The serialized start either precedes denial and may finish boundedly, or is rejected. Evidence distinguishes acceptance from literal first guest instruction. |
| Authorization expires while route data remains | No new invocation/child start; authorized management can still inspect bounded historical route data. Retention does not refresh grants. |
| Route envelope expires while authorization appears current | Route selection/start is denied until a current exact envelope and matching authority are installed. |
| Signature/evidence, caller identity or capability grant expires earlier | The stricter bound wins; a longer lease cannot extend it. |
| Authority lease renewed, unchanged route bytes | A fresh consistent authorization checkpoint may extend the permitted window; route generation/digest alone does not. Duplicate renewal cannot reset its original expiry/contact time. |
| A revoked; B shares A's component or package | B remains usable only under its own tenant publication/lease. A cannot use B's grant, lifecycle generation, provider secrets or prepared authority. |
| Policy/trust/profile changes without route change | Changed bindings lose permission. Preserving an unchanged binding requires an authenticated decision from the newer checkpoint. Unsupported host/provider profiles fail. |
| Restart with old snapshots, floors and lease | History can load; execution stays denied until new-boot authentication, clock validation and a fresh current lease. Restart while partitioned cannot extend old permission. |
| Delayed lower sequence / same sequence with different digest | Old update is rejected; conflicting digest fails explicitly. Neither overwrites floors or renews contact time. |
| Reordered delta / missing page / dropped deletion | No mixed authority cut becomes usable. Request a complete checkpoint, with bounded staging; incomplete absence grants nothing. |
| Authority epoch change, unknown issuer or wrong node/boot audience | Reject unless the currently trusted transition and fresh complete checkpoint are verified. Numeric ordering alone is insufficient. |
| Clock rolls back, jumps forward, exceeds uncertainty, or loses continuity | No deadline extension; invalidate as needed and deny until verified time/authority recovers. Exercise suspend/resume, VM migration and the exact expiry boundary. |
| Route rollback or original operation receipt replay | Rollback requires a new generation and current captured-publication permission. Replay returns history without reinstalling old routes or leases. |
| Reconnect after unseen revoke and several policy updates | Verify current checkpoint and floors before resuming; A remains denied, unrelated eligible B can resume. Stale queued exact pins are rejected rather than silently retargeted. |
| Oversized checkpoint, full replay-floor store, canceled verification or stalled renewal | Reject/bound new work. Preserve security floors and keep actual owners charged through cleanup. A stalled worker cannot delay expiry enforcement. |
| Parent accepted before expiry, descendant/provider operation begins later | Parent may complete under its original limits; the new operation independently checks current authority. Uncertain already-issued external effects are reported without blind retry. |
| Unavailable controller after expiry, valid management identity | Status remains bounded and reports expired authority; it does not issue a local fallback grant or enumerate another tenant's publications. |

## Required evidence package

Record the source/binary and protocol/profile versions, exact configuration,
clock source/uncertainty/drift contract, authority/node boot identities, checkpoint
sequences, publication associations and injected event order. For each case retain
expected and actual start decisions, cutover timing, restart/floor observations,
owned-resource return and independent-node/publication outcomes. Redact tokens,
lease bodies, keys and private payloads. Use a compact bounded summary plus the
minimal failure diagnostics, not unbounded per-request logs.

The Phase 5 entry review must validate the proposed wire/storage/clock designs
against every matrix row before implementation claims. The Phase 5 completion
gate requires the real executed results, including denial cases and absence of
control-plane RPCs on the ordinary hot path. A model-only result, a green local
unit suite or a claimed timeout without observed cleanup is insufficient.
