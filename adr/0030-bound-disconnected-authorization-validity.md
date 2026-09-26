# ADR-0030: Bound disconnected authorization validity

- **Status:** Accepted
- **Date:** 2026-09-13
- **Issue:** #274
- **RFC:** [RFC-0004](../rfcs/0004-route-and-authorization-freshness.md)
- **Clarifies:** ADR-0011's temporary use of a last valid route snapshot

## Context

Immutable route data can remain correct while permission to use a publication
has expired or been revoked. A disconnected future node cannot guarantee both
indefinite availability and immediate knowledge of an unseen remote revocation.
The standalone runtime already rechecks exact local publication authority at
guarded start; this is not distributed freshness.

## Decision

Keep local route resolution without a synchronous control-plane request on every
invocation. Separate route content/lifetime from authorization leases and
lifecycle, evidence, trust and capability-policy freshness.

Future cluster execution requires finite node/audience-bound leases over exact
tenant publications, route identities and consistent authority checkpoints.
RFC-0004 selects a 30-second lease/disconnection default and a 300-second hard
ceiling, intersected with stricter node/issuer settings and all underlying
expiries. Route retention never extends permission. Time checks use conservative
bounded uncertainty and monotonic deadlines; unknown clock continuity denies
starts. Restart needs a fresh authenticated checkpoint/lease for a new boot
incarnation, even when cached routes remain available.

Install authority and replay floors before exposing grants. Reject reordered,
ambiguous, stale or incompatible updates. Known revocations cannot be undone by
route rollback, cache hits, receipt replay or renewal of unrelated publications.
Rollback issues a new monotonic route targeting the captured publication and
independently checks its current authority.

The final local guarded-start decision is the cutover. Queued, prepared and
ready work still requires current exact permission. Previously accepted work may
finish within its own finite deadline/resources; child starts and new provider
operations require their own current authorization. No unseen-revocation kill,
automatic external retry or premature resource refund is promised.

## Consequences and delivery

"Temporary" means the intersection of authenticated route/lease validity,
maximum disconnection, local currentness and activation deadlines. Expired
authorization denies new starts while bounded route/history inspection may
continue. Availability during a partition is deliberately finite.

This is the Phase 3 design delivery, not implemented clustering or new standalone
configuration. Phase 5 owns versioned protocols, controller transactions,
trusted clock/platform support, durable anti-replay state, reconnect, bounded
shared owners and the executable
[scenario matrix](../docs/architecture/cluster-freshness-handoff.md).
Cluster support requires that evidence before entry/acceptance claims. No
per-service control channel, refresh worker, execution allocation or heavy load
campaign is introduced here.
