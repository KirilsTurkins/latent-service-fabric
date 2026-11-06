# Plan publication storage and maintenance

Keep room for the next release, its rollback target and recovery work. Retirement
makes a publication ineligible; it does **not** free committed files. Releases
consume publication, content and metadata budgets even when assets are unchanged.

## Inspect remaining capacity

Collect an inventory with your existing operator profile, then summarize it with
the maintained Node.js helper:

```sh
latent --config "$ClientConfig" --profile operator --output json node get "$Node" > inventory.json
node tools/catalog-capacity.mjs inventory.json
```

The report shows used, maximum and remaining content bytes, content metadata,
shared blobs, publications, recovery directories and publication-index metadata.
It also reports the maximum files allowed in one publication. Decimal counters
remain exact. Unavailable data requires a fresh inventory; the helper never
invents zero usage or retries a mutation.

Schedule maintenance when **any** budget reaches 80%; stop promotions by 90%,
or sooner if the next measured package and recovery reserve will not fit. These
are planning guidelines. An inventory reserves no capacity for a later publish.

Save observations after a finite representative release sequence. Compare each
budget's changes, including evidence renewal and failed-publication cleanup.
Use the largest observed increase and your selected rollback history to reserve
headroom. Package size alone cannot predict every budget.

## Understand disk usage

The catalog charges every publication link's full length plus each shared blob
once. Hard links can share a physical inode, so logical charges can grow faster
than allocated disk bytes. Both matter. On the qualified Linux host:

```sh
du --summarize --block-size=1 "$DataDirectory"
df --block-size=1 "$DataDirectory"
df --inodes "$DataDirectory"
```

`du` normally counts hard-linked data once. Filesystem metadata, allocation units,
sparse files and snapshots affect the result. Use stopped measurements for a
consistent maintenance inventory. The capacity helper leaves physical allocation
unmeasured. Audit, lifecycle history, other catalogs and protected configuration
also need storage outside the publication content ledger.

## Choose a maintenance window

For terminal unreferenced payloads, use the explicit
[publication deletion workflow](publication-deletion.md) with mandatory durable
audit. It does not compact independent history. Other choices remain a reviewed
increase of a finite limit, storage expansion or reprovisioning of an independent
empty installation. The following stopped workflow applies to expansion/restore.

1. Stop release jobs and other mutations. Record exact current publications,
   GET/HEAD routes, deployments, evidence and retained rollback targets.
2. Drain traffic and stop the node cleanly. Preserve a complete stopped backup of
   its data, protected configuration, credentials, trust/revocation history and
   external policy files. Keep it private; preserve ownership, modes and hard
   links. Do not activate a partially copied backup.
3. For expansion, review physical capacity and every configured ceiling. Reopen
   the complete installation with its compatible runtime; verify readiness,
   current routes and eligible rollback targets.
4. For reprovisioning, use a separate empty installation. Carry forward current
   trust and revocations, verify and explicitly publish reviewed eligible
   packages, then apply routes with the [recovery workflow](static-route-sets.md).
   Retain eligible earlier publications for rollback. Historical successful
   receipts do not authorize fresh admission.
5. Keep the replacement private until every intended route works. If interrupted,
   recover its original operation IDs; UNKNOWN does not permit publishing again.
   Keep the stopped original intact for recovery. Never merge individual rows
   between installations or run both against one data root.

Reprovisioning creates new operation history. It is not in-place compaction or
automatic migration. Measure and announce downtime. A restore drill must verify
exact content, routes, current eligibility, protected policy, rollback and clean
restart on the selected filesystem.

The maintained native static-site workflow exercises a complete stopped restore
on local Linux storage, including preserved hard links/modes, a larger finite
publication limit, unchanged history and an explicit rollback. Its receipt is
`catalogCapacity.stoppedRestoreAndExpansion`. This does not qualify an arbitrary
backup product or network filesystem; repeat the drill on your selected storage.

The [retention decision](../../adr/0050-plan-capacity-before-deleting-publication-history.md)
defines the bounded deletion protocol. Current orphan cleanup retains committed
publications, shared content and live preparation sources. Do not remove catalog
directories, rows, lock files or format markers by hand.


## Payload deletion is separate from history compaction

The [operator deletion guide](publication-deletion.md) covers snapshots, rollback
pins, terminal visibility removal, read-only reclamation assessment, explicit
cleanup, capacity facts and original-operation recovery. It uses authenticated
management requests and mandatory durable audit; there is no no-op audit fallback.
A tombstone retains its payload charges until a separate durable cleanup finishes.
Capsule and componentless-web cleanup preserve shared blobs until their last
committed reference and synchronize removal before refunds.

Independent lifecycle/evidence/web history and compact negative identity budgets
remain charged. Payload deletion is not permission to compact those histories,
trust/revocations, business state or audit. Stop and preserve the whole coupled
installation for backup/restore; never merge individual protected roots. An
assessment is only a diagnostic and grants no permission for a later unlink.
