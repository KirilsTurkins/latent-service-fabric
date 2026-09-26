# Atomic eligible-release rollback

A [durable rollout](phase-2-rollouts.md) retains one restoration target: the exact
base deployment immediately before Start. An explicit Rollback restores that
content through a **new** route generation. It does not rewind generation numbers
or restore execution permission to a revoked release.

## Target and preconditions

New rollout plans bind a `rollbackTarget` containing format version 1, the
historical global route generation and the digest of the retained base manifest.
That manifest already contains the original weight, grants, resources and
placement. No additional route snapshot or arbitrary historical release list is
retained. The target is immutable and part of the plan digest.

The authenticated tenant administrator supplies the rollout ID, exact current
rollout revision, operation ID and `targetGeneration` matching that single target.
The target generation is a compare precondition; it does not select arbitrary
historical catalog content. The new receipt reports the restored target separately
from its newly published `routeGeneration`.

Rollback is permitted from Running, Paused, Completed or Aborted when the current
deployment cohort still exactly matches the rollout's last applied cohort. A
manual deployment edit, different revision or target, or already RolledBack state
rejects a fresh request. A retained exact operation retry still returns its
original receipt. Historical stage and policy remain available for inspection;
they no longer describe the restored route weights.

Rows created before rollback-target support remain readable and replayable. They
have no plan-bound target and reject a fresh rollback with
`rollout-rollback-target-unavailable`. An old object generation or an evicted Start
receipt is not enough to invent that provenance.

## Eligibility and compatibility

The target must still be available, intact, correctly associated with its exact
package and currently eligible for the tenant, runtime profile and configured
trust policy. Missing, corrupt, expired, revoked, retired or incompatible target
content cannot be reintroduced. Normal resource admission and final publication
fences still apply.

Compatibility is checked in the replacement direction: candidate to restored
base. Earlier base-to-candidate compatibility does not establish the reverse.
Signed packages use their exact retained package and paired WIT inputs;
trusted-local artifacts use conservative descriptor comparison. Unknown,
unsupported or breaking replacement is rejected. For example, removing an API
added by the candidate can prevent this conservative rollback.

The replaced candidate may itself have become ineligible. Its owner-bound
historical metadata and package bytes are read only to establish integrity,
association and compatibility; that read grants no execution permission. Those
source bytes must still be available and intact. Missing signed-package inputs
cannot fall back to an unsigned descriptor comparison.

## Atomic publication and invocation pins

Preparation removes the candidate and restores the original base manifest,
including its original weight. Unrelated deployments remain unchanged. The base
object and compiled routes receive a fresh monotonic generation; routes, the
RolledBack disposition and the committed receipt share one catalog transaction.

The final writer compares both the captured state version and route generation.
Concurrent manual publication, promotion, pause or rollback conflicts rather than
rebasing the prepared restoration. Already running invocations retain their
original revision and budget; later selections see the complete restored base.
Execution-time revocation fencing continues to apply to retained pins.

Rollback uses the existing bounded prepared owner, coordinator worker, command
queue, response allowance and receipt ring. It requires no canary observation or
new node setting. A committed rollback retires the existing observation window;
live sample owners keep their quota until actual release. It does not register a
new canary interval.

## Audit, retries and recovery

The critical audit attempt records the caller's expected target generation. A
committed conclusion records the validated historical target and the new route
generation separately, linked to the exact receipt digest. Known rejection is
audited without creating a committed catalog receipt. Response and audit size
preflight occur before critical acceptance.

A failure before rename leaves the previous complete publication authoritative.
If rename succeeds but directory synchronization fails, the process installs the
whole restored publication and reports uncertain durability. Timeout or a missing
acknowledgement does not undo that publication. Use the original operation ID and
exact request for retry or lookup, and inspect the returned receipt and audit
acknowledgement.

Restart recovers the complete selected publication and reconciles pending audit
attempts against retained receipts. An exact committed retry never re-applies
routes or renews permission, even if authority later changes. Evicted or
never-committed receipt lookup returns Unknown, which does not establish absence
of a past commit. Retained rollout identity and revision checks prevent a stale
request from becoming a fresh rollback after receipt eviction.

See the [management API reference](reference/management-services.md),
[audit contract](phase-2-audit.md) and [routing semantics](deployment-routing.md).
