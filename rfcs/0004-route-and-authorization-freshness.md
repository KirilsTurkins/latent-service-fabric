# RFC-0004: Route and authorization freshness

- **Status:** Accepted
- **Authors:** Latent Service Fabric maintainers
- **Created:** 2026-09-13
- **Target milestone:** Phase 3 design; Phase 5 implementation
- **Accepted by:** [ADR-0030](../adr/0030-bound-disconnected-authorization-validity.md)
- **Delivery:** [#274](https://github.com/KirilsTurkins/latent-service-fabric/issues/274)

## Summary

An immutable route is data, not continuing permission to execute. A future
cluster node may resolve locally while its exact route, publication and
authorization remain valid under a finite lease. It stops admitting new work
when any required validity bound expires, even if useful route data remains.
No ordinary invocation needs a synchronous control-plane request.

This RFC defines the Phase 5 implementation contract. Distributed leases,
route watches, remote authorization and the settings below are **not implemented
or configurable in the current standalone node**. Phase 3 delivers the decision,
scenario matrix and implementation handoff, without claiming distributed tests
have run. The current local guarded-start checks remain mandatory.

## Motivation

ADR-0011 permits temporary use of the last valid snapshot without defining
"temporary" across a partition. A disconnected node cannot learn an unseen
remote revocation immediately. Finite authorization validity makes the maximum
window explicit; immutable route retention alone cannot provide that guarantee.

[ADR-0027](../adr/0027-separate-publication-authority-from-component-identity.md)
also makes the authorized object an exact scoped publication, independently
from component deduplication. Renewing a route or finding the same compiled
component must never refresh another publication's permission.

## Detailed contract

### Distinct identities and authorities

The future distribution protocol must authenticate these complete associations.
The fields below are requirements, not a new wire schema or reinterpretation of
existing Protobuf fields.

| Object | Required identity and validity |
| --- | --- |
| Route content | Catalog identity, tenant, immutable snapshot digest and monotonic route generation; exact deployment/revision and captured publication for each target. The existing reserved publication attribute and typed pin must agree. |
| Route distribution envelope | Issuing cluster/authority epoch, monotonic distribution sequence, content digest, audience and absolute route-use expiry. Reissuing unchanged content requires a new authenticated envelope, not a local timestamp update. |
| Publication | Exact `PublicationRef` (tenant and publication ID), immutable package digest and component digest. Lifecycle generation/state and selected evidence revision are separate mutable authority inputs. |
| Authorization checkpoint | Issuing authority epoch/sequence and digest of the complete applicable policy state: lifecycle, publisher/builder trust, grant-policy and required host/isolation profiles. A route generation is not a policy epoch. |
| Node authorization lease | Unique lease ID, cluster/catalog, tenant, exact permitted route envelope/content, publication/evidence/lifecycle and policy checkpoint, node identity and fresh boot incarnation, not-before/not-after, and finite negotiated ceilings. |
| Activation pin | Exact deployment revision, route generation/digest, publication and the locally verified authority checkpoint/lease used at guarded start; original deadline, principal and delegated budget remain distinct. |

Package/component digests are consistency assertions, never substitutes for the
scoped publication. A lease grants only the intersection of its permitted
operations, current local policy and the authenticated caller's grants. It
cannot install a provider, select an unsupported host or widen a descendant's
authority. Local-unscoped trusted-local publications are not remotely admissible
under this profile; an explicit scoped publication is required first.

All objects are checked against the configured cluster/catalog and node audience.
A verified signature or an authenticated transport alone is insufficient. The
receiver verifies content, complete associations, current trust, sequencing,
validity and local admission. Publication and lifecycle authority remain
independent for packages or tenants that share executable bytes.

### Finite validity and outage policy

The selected, unsupported `lsf-route-lease-v1` Phase 5 profile defines these policy defaults and hard
ceilings. They are design choices to validate at Phase 5 entry, not measured SLOs
or current command-line options. Changing these ceilings requires a reviewed
profile revision; operators may select stricter values.

| Bound | Default | Allowed ceiling / rule |
| --- | --- | --- |
| Authorization lease duration | 30 seconds | Positive, at most 300 seconds, and no later than any underlying evidence, identity or policy expiry. |
| Maximum disconnection from a verified current authorization checkpoint | 30 seconds | Positive, at most 300 seconds and no greater than the selected lease-duration ceiling. |
| Usable route-envelope lifetime | 1 hour | Positive, at most 24 hours. Retention for inspection is separately bounded and conveys no execution permission. |
| Accepted uncertainty of authoritative time | 1 second | Nonnegative, at most 5 seconds; a platform unable to maintain the selected bound denies starts. |

The issuer's policy and the node's configured maxima are intersected, never
added. Zero, overflow, unbounded sentinels and inconsistent settings are rejected.
Renewal requires a new authenticated lease after current authorization checks;
a heartbeat, route download, successful invocation, duplicate message or local
cache hit cannot extend permission. Contact time advances only after a fresh
current checkpoint has been authenticated and accepted; TCP traffic alone does
not reset the disconnection timer.

At guarded start the node requires **all** of the following:

1. The exact route and publication associations are available and verified.
2. Their current local lifecycle, evidence, grants and required profiles permit
   execution; no known denial or revoked trust has been bypassed.
3. The accepted lease/checkpoint is current for those exact inputs and audience.
4. Authoritative time is provably within every not-before/not-after interval,
   and the route-use envelope has not expired.
5. The conservative monotonic disconnection deadline has not been reached.
6. The activation still has its own unexpired deadline and owned resource budget.

Equality with an expiry is denial. The earliest deadline wins. Expired routes or
leases may remain inspectable within retention limits, but cannot select work.
Failure of one publication or tenant does not invalidate an unrelated valid
lease, unless their shared authority/profile itself has become invalid.

If a revocation is not delivered, new starts may remain possible until the
previously issued permission expires. For an online node, installing a denial
ends that permission at the local guarded-start boundary. For a partitioned
node, the last valid lease and disconnection bounds limit the window; the
initial profile permits no more than 300 seconds from the last authorized
checkpoint, with expiry checks made conservatively for clock uncertainty.
This is a bound on **new start decisions**, not on completion of accepted work.
There is no indefinite-availability or immediate-unseen-revocation promise.

### Clock and restart assumptions

The clustered security profile must supply a trustworthy bounded interval
`[earliest, latest]` for authority time, a monotonic elapsed-time source with a
declared drift bound, and a detectable boot incarnation. A raw wall clock or an
NTP success flag is not by itself such a guarantee. Clock trust/uncertainty is
part of the platform profile, including suspension and VM migration behavior.

Accept a validity interval only when `earliest >= not_before` and
`latest < not_after`. Derive a conservative local monotonic deadline at receipt,
including the configured drift bound; retain the earlier deadline across later
clock observations. A backwards clock adjustment cannot extend an existing
lease. A forward jump, uncertainty beyond the selected bound, lost monotonic
continuity or inability to detect suspension invalidates it until revalidation.
Future-dated checkpoints cannot repair clock uncertainty by assertion.

Restart loads verified route data and durable replay floors for inspection, but
does **not** resume a previous process's lease. Before accepting execution the
node obtains a fresh authenticated checkpoint/lease bound to a new unpredictable
boot challenge and establishes a trusted time interval. Restart during a
partition therefore denies new work even if retained routes look recent.
The existing standalone policy/clock floors continue their own local contract;
they are not a distributed clock or lease implementation.

### Ordering, replay and installation

Persist the accepted authority epoch, checkpoint sequence/digest and relevant
route distribution floors before exposing newly authorized routes. A checkpoint
is one consistent authority cut. Independently received pieces may be staged
within finite bounds but never assembled into a speculative grant.

- Lower epochs/sequences are rejected. The same sequence with different content
  is corruption/conflict, not last-writer-wins. An exact duplicate is idempotent
  and preserves the original expiry and contact deadline.
- A delta must name its exact predecessor. Missing predecessors, reordered
  fragments and unverifiable deletions require a fresh complete checkpoint;
  absence of a row in an incomplete page never revokes or grants permission.
- A changed lifecycle/evidence/trust/grant/profile invalidates leases depending
  on that change. An unchanged binding may remain usable only when the newer
  authenticated checkpoint explicitly preserves it. A stale lease cannot decide
  that newer policy is irrelevant on its own.
- Denials and durable floors are installed before acknowledgements. A retained
  positive route, old signature, old renewal or receipt cannot undo a revocation.
  Revoked/retired publication transitions retain their existing lifecycle rules.
- An authority epoch change requires a currently trusted, explicit transition
  plus full revalidation. New leader identity or a larger number alone grants
  nothing. Loss/corruption of floors requires authenticated bootstrap recovery,
  not deletion of floors or trusted-local fallback.
- Rollback publishes a **new** route generation/envelope targeting the captured
  publication and obtains current permission for it. Restoring an old snapshot
  or replaying an operation receipt never recreates a lease or grant.

Replay floors and tombstones have finite durable ownership. When safe compaction
requires a full checkpoint or authority contact, a full/disconnected node denies
new admissions instead of evicting security floors. Restoring arbitrary older
disk images is not an anti-rollback guarantee: the trusted host/storage boundary
and fresh online bootstrap must be explicit in the Phase 5 threat model.

### Cutover, queues and descendant work

Preserve `ReleaseUseEligibility::with_current` and the admission authority's
guarded-start contract. The decision is serialized with relevant authority
installation, not with the first literal guest CPU instruction. Route resolution,
queue acceptance, preparation, native-cache lookup and readiness alone do not
cross this boundary. Each queued/ready activation rechecks the exact pin and
all validity bounds at its final start decision.

An activation accepted before a subsequent denial/expiry may finish under its
already bounded execution deadline and resources. It is not promised an
instantaneous remote kill. Any additional cancellation policy must report actual
cleanup; it cannot refund a still-live Store, provider or child. New child starts
and new provider operations require their own current authority and conserved
descendant limits; an accepted parent does not extend a lease or bypass a known
revocation. Already-issued external effects keep the explicit uncertainty rules
of ADR-0025, with no automatic retry or rollback promise.

Remote invocation carries the exact scoped publication, revision, route and
delegation. The receiver independently validates its own lease/currentness and
the caller's delegated deadline/budget. It executes that selection or rejects;
it cannot reroute to a different publication with the same component digest.

### Reconnect and failure reporting

Reconnect authenticates the authority, obtains a fresh complete checkpoint (or
verified contiguous deltas), reconciles floors/denials and trusted time, verifies
required local publications, and atomically installs eligible routes/leases.
Only then may fresh starts resume. A stale queued request may be rejected; any
caller-authorized reroute is a new selection with the remaining original budget,
never a silent repair of an exact revision pin.

Operators need bounded, tenant-scoped diagnostics for route availability,
authorization validity/expiry, last verified checkpoint, disconnection, clock
uncertainty and installed floors. Distinguish unavailable authority from an
explicit policy denial and from a caller deadline. Public responses must not
enumerate foreign publications or publish signatures, credentials or lease
payloads. Future wire error details are versioned by the Phase 5 protocol work;
this RFC does not assign new meanings to current error fields.

## Compatibility and migration

The [standalone implementation](../docs/reference/publication-runtime.md) remains
the executable baseline: held routes/prepared entries carry exact publications,
and current local lifecycle/admission is checked at guarded start. Local checks
do not establish freshness relative to a remote controller that does not yet
exist. Legacy `ReleaseDigest` remains the component digest.

Phase 5 introduces versioned distribution/lease protocols and storage formats.
Old readers and unsupported profiles fail closed. Standalone deployments do not
silently acquire cluster settings, remote admission or a clock dependency from
this Phase 3 documentation change.

## Resource-allocation and trust-boundary impact

Use fixed/shared bounded route-watch, verification, renewal and reconciliation
owners. Configure limits for pending envelopes, bytes, publications per lease,
signatures, comparison work, staged deltas, leases, timers, floors and diagnostics.
No dormant service gains a connection, refresh task, thread or timer. A shared
expiry structure and currentness checks enforce deadlines even if renewal work
stalls. Canceled work remains charged until physical cleanup or bounded transfer.

The controller must serialize lease issuance with revocation at an authoritative
cut and never issue fresh permission after a committed denial. Distributed
controller/storage consistency, authenticated node identity, clock bounds and
protected replay floors are required parts of the Phase 5 trusted computing base.
This RFC does not claim they follow automatically from Wasmtime or immutable
snapshots. No distributed safety claim is made before their tests pass.

## Alternatives

Unbounded use of cached routes is rejected because it has no revocation-freshness
bound. A synchronous authorization request for every invocation is rejected as
the default because it couples ordinary calls to control-plane availability.
Using route generation as authorization freshness is rejected because unchanged
routes can outlive a revocation or trust change. Killing all accepted work at
lease expiry is not the initial contract; later stronger profiles must prove
their actual cancellation/containment behavior separately.

## Validation plan and Phase 5 handoff

The [conformance matrix and implementation owners](../docs/architecture/cluster-freshness-handoff.md)
are normative Phase 5 entry requirements. Phase 3 validates documentation links
and consistency with the existing local cutover/publication contract. It does
not execute simulated distributed tests and label them production evidence.

## Open questions

None block this design handoff. Phase 5 must choose and verify the wire encoding,
checkpoint distribution/storage transaction, clock-provider implementation and
finite resource defaults before advertising support. Those implementations must
satisfy the selected identity, expiry, ordering and ownership semantics above.
