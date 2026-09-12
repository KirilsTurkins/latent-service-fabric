# Control-plane architecture

The control plane owns desired state, release eligibility and compiled route
metadata. Ordinary invocation selects a local immutable snapshot; it does not
wait for a deployment compiler, audit worker or rollout coordinator.

The [standalone Linux node](../reference/standalone-node.md) embeds the delivered
Phase 1 and Phase 2 control services. Phase 2 feature delivery includes package
admission, lifecycle, compatibility, audit, staged rollout, canary promotion,
rollback and [operator workflows](../phase-2-operator-workflows.md).
[Gate #158](https://github.com/KirilsTurkins/latent-service-fabric/issues/158)
remains pending. The separate `latent-control` application is a scaffold;
PostgreSQL, remote route watches and distributed reconciliation belong to Phase 5.

## Release catalog and admission

The directory catalog retains immutable component bytes, descriptor, capsule
manifest, contracts and a completion record binding their association.
`ReleaseDigest` identifies component bytes. Packaged content additionally has an
independent `PackageDigest` identifying its exact OCI manifest. A registry pull
or local verification report grants no catalog permission.

[Enforced admission](../reference/package-admission.md) checks package semantics,
tenant ownership, current publisher and independent builder policy, provenance,
SBOM requirements and the supported runtime profile. Durable policy/clock floors
and current shared authority constrain the resulting sealed grant. Explicit
trusted-local catalogs remain supported without inventing a signed proof.

Both modes use [release lifecycle](../reference/release-lifecycle.md). Per-release
records, a bounded receipt ring and one roll-forward intent commit admission,
revocation, retirement or evidence renewal. An initialized catalog does not
automatically adopt an orphan complete directory after interruption. Immutable
original evidence remains retained; renewal storage bounds the selected and
pending revisions and reclaims only verified unreferenced owned content.

Historical descriptors and receipts are observations. Runtime and route
compilation require a capability from the exact configured catalog, plus current
admission authority in enforced mode. An expired proof can leave a verified
historical row available to management while execution remains denied. Corrupt
content and invalid durable associations still fail recovery.

## Contracts and policy

[Compatibility](../reference/release-compatibility.md) has two bounded paths:
conservative descriptor comparison, and exact old/candidate package comparison
using temporary WIT resolvers. Reports distinguish identical, backward
compatible, breaking, unsupported and unknown shapes. An explicit allowance is
bound to the exact compared pair; it cannot approve unknown or unsupported
analysis, bypass import uncertainty or grant release eligibility.

The runtime's actual target, engine and CPU requirements are checked separately.
General consumer/provider binding compilation and policy-managed capability
providers remain Phase 3 work. Current host imports are context, structured log
and monotonic/wall clock; declaring another WIT package does not supply a provider.

## Combined deployment publication

`DirectoryDeploymentRepository` owns desired deployments, compiled routes,
rollout rows and finite committed operation histories in one publication.
Preparation derives the complete candidate and its bounded encoded bytes.
Commit checks object, route and combined state preconditions under the actual
writer lock, then replaces the catalog atomically under current release fences.
It never commits a rollout journal separately from the routes it describes.

Object generations identify the last mutation of each deployment. Route
generation changes when a new executable snapshot is published. The combined
state version also advances for control-only changes, including pause and abort.
Existing activations retain their old route pins. A newly selected or queued
activation still needs current release permission at its final start decision.

[Managed deployment operations](../phase-2-operator-workflows.md#managed-deployment-receipts)
add caller-retained operation IDs, exact object and global state preconditions,
sealed preparation and synchronous commit. Exact retained replay returns the
original receipt before fresh preconditions; it publishes nothing. Finite
retention means `Unknown` includes both unseen and evicted operations. The
original state precondition prevents an evicted create from executing again
after an intervening delete. Legacy writers preserve both operation histories.

Format 3 combines routes and rollout history; format 4 adds managed deployment
receipts. Formats 1 through 3 retain their existing absent-field and checksum
rules. The first managed deployment operation writes format 4. Lowering limits
does not silently prune retained state.

Compilation still visits the bounded desired state and encodes a complete
catalog candidate. Fresh verified metadata can reuse immutable derivations and
unchanged packed tenant/service scopes. These are bounded update costs, not a
claim of constant work per deployment change; see
[deployment routing](../deployment-routing.md#limits-and-update-cost).

## Rollout control

One fixed [rollout coordinator](../phase-2-rollouts.md) serves a bounded queue.
Start captures an explicit base/candidate plan; manual advance and resume reuse
the existing compiler and final publication fences. Pause and abort persist
control state while preserving current route weights. Restart restores committed
progress and does not advance a stage automatically.

[Canary promotion](../phase-2-canary-promotion.md) is explicit. A full, drained
observation interval must match the configured telemetry owner, exact rollout
revision, compiled cohort and policy. The store consumes sealed evidence and
rechecks it with current eligibility at publication. A diagnostic evaluation or
caller-supplied success flag cannot promote a stage.

[Rollback](../phase-2-rollback.md) restores the immutable pre-Start base captured
by a new plan. It publishes a new monotonic generation and records the historical
target separately. Historical source metadata permits reverse comparison even
when the candidate is now denied; the target independently needs current
eligibility. Old plans without a retained target remain readable and replayable
but cannot perform a fresh rollback. Neither rollback nor replay restores a
revoked release.

## Audit and bounded ownership

Optional [durable audit](../phase-2-audit.md) uses one shared worker, private
storage, typed records and bounded query owners. Critical mutations reserve an
attempt and outcome, validate prospective response capacity, and make the
attempt durable before mutation starts. Audit waits occur outside catalog and
authority fences. Verification diagnostics may be observed earlier; they do
not assert a publication occurred.

Catalog disposition, directory-sync confirmation and audit acknowledgement are
independent. A committed change with a lost response or failed terminal audit
may have an unknown audit outcome. Startup reconciles exact retained receipts;
it never repeats an operation to guess its outcome. Revoke alone may continue
when the audit ledger is unavailable, with an explicit gap and its ordinary
durable lifecycle transaction still required.

Audit retention rejects new records when full. Release, deployment and rollout
operation rings instead retain finite recent history. Neither policy creates a
per-service worker. Read/response leases survive canceled waiters through actual
work and final response ownership. Shutdown stops new work and reports unfinished
owners truthfully rather than refunding resources still in use.

## Current and future boundaries

The node reports bounded local identity, runtime, class, cell, queue, cache and
control-owner observations. Phase 3 adds shared provider pools, durable capability
policy, exact bindings and application ingress. Cluster inventory, region/zone
placement, state affinity and a separate persistent control service are later
phases. A local snapshot remains usable only while its own lifecycle, trust and
runtime requirements remain valid; loss of a remote control service cannot
turn stale authority into permission.
