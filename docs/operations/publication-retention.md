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

There is no command to delete committed history. Current choices are a reviewed
increase of the relevant finite limit, storage expansion or explicit
reprovisioning of an independent empty installation.

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

The [retention decision](../../adr/0050-plan-capacity-before-deleting-publication-history.md)
defines the future deletion protocol. Current orphan cleanup retains committed
publications, shared content and live preparation sources. Do not remove catalog
directories, rows, lock files or format markers by hand.
