# Durable single-node rollouts

Phase 2 issue #153 adds an optional manual rollout coordinator over the existing
embedded deployment catalog. It has one shared bounded worker and persists each
committed operation together with the complete route state. It does not add
background service instances or automatically advance stages.

## Plan and transitions

A plan names a tenant, service, retained rollout ID, one existing base deployment
with its exact object generation, and one explicitly named new candidate. Both
deployments must have the same tenant, namespace and service, and different
component identities. Start supports a cohort containing only that base; it
rejects broader cohorts and existing candidate IDs.

Candidate weights are integer basis points, strictly increasing from 1 through
10,000, with 10,000 required as the last stage. The base receives the remainder.
The final stage atomically removes the base deployment, so no zero-weight object
is installed. Each stage preserves the original manifests apart from the planned
weight changes.

| Operation | Required state | Effect |
| --- | --- | --- |
| Start | New rollout ID, expected rollout revision 0 | Installs stage 0; becomes Running, or Completed if this is the final stage. |
| Advance | Manual plan, Running, exact revision and next stage | Installs the next weights; the last stage becomes Completed. |
| Promote | Canary plan, Running, exact revision and next stage | Requires complete exact-cohort evidence, then atomically installs the next weights. |
| Pause | Running, exact revision | Becomes Paused; retains the existing executable route snapshot. |
| Resume | Paused, exact revision | Rechecks and republishes the current stage with current release grants; becomes Running. |
| Abort | Active rollout, exact revision | Becomes Aborted; preserves the currently installed routes. |
| Rollback | Running, Paused, Completed or Aborted; exact revision, retained target and unchanged cohort | Restores the original base through a new generation; becomes RolledBack. |

Abort does not restore the original deployment. Completed and aborted plans do
not continue advancing. [Canary evaluation and promotion](phase-2-canary-promotion.md)
add explicit declared acceptance criteria. [Rollback](phase-2-rollback.md) restores
the plan-bound original base after current eligibility and reverse compatibility
checks; it preserves historical progress while replacing the installed cohort.

Before a forward route-changing operation, the coordinator checks current
tenant-scoped release eligibility and conservative old-to-candidate compatibility.
Rollback checks the replacement direction and independently authorizes its target;
a historical read of the replaced candidate does not require renewed permission. Signed
packages use exact retained package and WIT input from the artifact catalog.
Reading historical input does not renew execution permission. Trusted-local
artifacts without packages use bounded descriptor comparison and reject unknown
compatibility. The normal runtime requirement, lifecycle and admission checks
still run at the actual catalog commit boundary.

## Atomic state and conflicts

The catalog publishes a combined immutable state containing the routes, rollout
table, transaction version and durability result. Each writer compares both the
captured transaction and route generation at commit. A concurrent ordinary
deployment edit therefore conflicts with an earlier prepared rollout, including
when one of the operations changes only rollout state.

Before advancing, resuming or rolling back, the current managed cohort must still match the
recorded deployment IDs, object versions and manifest digests. The coordinator
does not overwrite an operator's intervening route changes. Pause and abort can
still stop progress after cohort or trust changes, without obtaining new grants.

Rollout revision, combined state version, route generation and deployment object
generation are separate identities. A pause advances the first two while keeping
the route snapshot. Invocation pins retain only that executable snapshot, so old
activations do not retain rollout history. Already admitted execution and
lifecycle fencing follow the existing [routing semantics](deployment-routing.md).

Catalogs without rollout history retain the existing version-2 format. The first
rollout uses a version-3 catalog document with one checksum and atomic rename for
routes, state and receipts. Legacy version-1/2 recovery remains supported. Restart
restores committed progress and never infers permission to advance automatically.

## Receipts, retries and uncertain outcomes

Every mutation supplies an operation ID and expected rollout revision. Start
expects revision 0; subsequent changes require the exact positive revision.
Committed operations increment the rollout revision and retain a canonical
receipt binding the tenant, actor, action, normalized request and resulting state.
An exact retained retry returns that receipt with a replay flag before checking
the newer current revision. Reusing its ID for different input conflicts.

The bounded receipt history contains committed operations. A request rejected
before commit has no committed receipt. An evicted or never-committed operation
lookup returns Unknown; that result is not proof that the operation did not run.
Retained rollout IDs are never recycled, and an old expected revision cannot
repeat a committed mutation after receipt eviction.

If rename succeeds but directory synchronization fails, the process installs the
whole combined state and reports uncertain durability. Lookup remains Uncertain
until an actual durability confirmation, successful recovery or later confirmed
complete commit. Client cancellation or timeout cannot undo a publication that
has already started. Retry and lookup use the same original operation identity.

## Audit, authorization and ownership

Enabling rollouts requires the node's same enabled [audit owner](phase-2-audit.md).
Preparation and complete response-size preflight happen before durable audit
acceptance. The worker reserves and durably records the attempt before commit,
then records the exact resulting receipt and acknowledgement. Audit I/O runs
outside invocation/currentness fences. A missing final durable acknowledgement
is reported explicitly; it does not relabel a committed catalog change as absent.

Startup reconciles pending rollout audit attempts against exact durable receipts
before the generic release fallback. This also applies when an operator omits
the rollout configuration after creating history: management RPCs are disabled,
while stored history and routes remain available to recovery.
Disabled management recovers within the documented hard ceilings. Reopening with
higher receipt limits preserves the original receipt ring capacity; the new
setting is a recovery ceiling, not a history resize operation.

Management RPCs authenticate tenant administrators and enforce tenant scope on
requests, lookups and filtered pages. Cursors carry page position, not authority.
The response allowance remains owned through protobuf encoding, the response
body and retained output frames. See the [management reference](reference/management-services.md)
and [standalone configuration](reference/standalone-node.md).

| Shared resource | Default | Hard maximum |
| --- | ---: | ---: |
| Active rollouts | 16 | 64 |
| Retained rollout rows | 256 | 1,024 |
| Stages per plan | 16 | 64 |
| Global committed receipts | 256 | 1,024 |
| Rollout metadata, including overlapping tables | 8 MiB | 32 MiB |
| Queued commands | 8 | 64 |
| Retained command bytes | 512 KiB | 4 MiB |
| One command | 64 KiB | 64 KiB |
| Response owners | 4 | 16 |
| One response page | 64 KiB | 64 KiB |
| Total response allowance | 1 MiB | 4 MiB |

Each page reserves four times its requested byte ceiling for overlapping output
representations. Queue admission also needs a response owner, so the limits work
together. The store permits one live prepared rollout mutation, bounds each
stored row to 128 KiB and each receipt to 4 KiB, and keeps the whole catalog within
its configured state-file limit. Full retention rejects new IDs; it does not
silently prune rollout identity or invent capacity.

Package comparison permits at most two retained sources of 32 MiB each during
the single prepared operation. Larger packages cannot use this rollout path;
the limit does not change ordinary artifact-catalog admission limits.

Shutdown first closes and joins the coordinator, then the audit worker and
control runtime. A timeout preserves actual accepted ownership and reports an
unclean shutdown. All rollout work is node-local; distributed reconciliation,
placement and consensus remain later phases.
