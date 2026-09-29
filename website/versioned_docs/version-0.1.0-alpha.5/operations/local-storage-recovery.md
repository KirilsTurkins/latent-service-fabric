# Preserve and restore local node state

Keep a node's complete durable state and protected configuration together. This
guide covers the node-owned local Linux container layout from
[Run a node in a Linux container](container-runtime.md). It uses UID/GID 10001 and
a local ext4 or XFS mount. The maintained drill records the actual filesystem;
qualifying one observed filesystem does not qualify every mount of its type.

Azure Files, NFS and SMB remain unqualified. There are no Azure resources in this
delivery, and local results do not establish remote storage durability. Use a
host-controlled Linux filesystem for the supported deployment alternative.

## What must survive together

| Root | Contents and recovery rule |
| --- | --- |
| `config` | Node identity, operator credentials, current admission policy/revocations, protected native key when used. Restore the reviewed set; do not generate replacement keys during recovery. |
| `data` | Publications, shared immutable blobs, lifecycle/evidence history, trigger/deployment state, operation receipts, audit and supply-chain clock floor. Restore the whole root. |
| `cache` | Cached artifacts and authenticated native receipts. Some caches can be rebuilt under their documented admission rules; this conservative snapshot preserves all of them. |

The filesystem must support same-filesystem hard links, stable open-file readers,
atomic replacement, successful file and parent-directory synchronization, reliable
exclusive locks between processes, ownership/mode checks and no-follow access.
It must not bypass those checks with shared write permissions or unsupported
extended ACLs. A failed durable operation can have an unknown result: retain its
operation ID and resolve its receipt/current state after recovery. Never remove
an intent, lock, format marker or catalog row to force startup.

## Stop and take a complete snapshot

The container entrypoint holds `.container-owner.lock` in the data root for its
process lifetime, including across native exec. The snapshot helper acquires the
same nonblocking lock. It rejects a running owner before creating a destination.
The lock file stays in place; stopping the owner releases the lock. Native
catalog locks continue to apply as well.

Use an administrative Linux session with UID/GID 10001. Make the source available
at `Installation/config`, `Installation/data` and `Installation/cache`, with the
same mounts as the container. Configuration in this helper's supported profile
is node-owned and private, rather than root-owned. Keep the node and all other
writers stopped throughout the operation, including policy editors:

```sh
docker stop --time 10 lsf-node
python3 tools/container_runtime/storage.py snapshot --source "$Installation" --output "$Backup"
```

`Backup` must be a new directory under a private directory you own. It must be
outside the source. The helper rejects symlinks, special files, external hard
links, foreign ownership, writable-by-others paths and extended ACLs. It preserves
hard-link relationships and modes, checks content before and after copying, and
syncs completed files and directories. Its bounds are 16,384 entries, 1 GiB of
logical file bytes and two minutes. A larger installation needs a separately
reviewed stopped filesystem snapshot procedure; never drop files to fit.

Only a complete verified copy receives `SNAPSHOT-COMPLETE.json`. A failed partial
directory remains for inspection and is not a restorable backup. Keep snapshots
private: they contain credentials and trust material. Store the authenticated
runtime image identity separately with your recovery records.

## Restore into a new installation

Keep the original stopped. Restore to a fresh directory; this tool never merges
rows into an existing installation or overwrites one:

```sh
python3 tools/container_runtime/storage.py restore --source "$Backup" --output "$RestoredInstallation"
```

It verifies the snapshot's complete manifest, bytes, permissions and hard links.
Mount the restored `config`, `data` and `cache` roots at the original container
locations, using the same approved runtime image. Wait for the retained
supply-chain clock lease, run the image's `check`, then start one owner and verify
authenticated readiness. Recheck current route targets, exact content and
original operation receipts before directing traffic to it.

An eligible earlier publication is selected through **new** explicit route
operations and current admission checks. Replaying an old receipt is a recovery
query, not permission to restore a revoked publication. Follow the
[route-set workflow](static-route-sets.md) for coordinated GET/HEAD reconciliation.
A runtime downgrade is separate and must obey the release compatibility policy.

## What the maintained test establishes

The real local-volume drill performs hard-link, held-reader/atomic-replacement,
file/directory sync, no-follow and separate-process lock checks as UID 10001.
A separate writer exits after syncing a pending file but before replacement;
the current file remains intact. The application drill publishes two signed
sites, restarts, updates only one, restarts again, and verifies the unchanged site
and exact operation receipt. It rejects a live backup, copies and restores the
stopped coupled roots, reopens their actual native catalogs, and selects an
eligible earlier publication while preserving the other site.

This covers orderly restart, interrupted local file replacement, native reopen,
stopped backup/restore and publication rollback. It does not inject a host power
failure or establish a storage service's physical write guarantees. Source-level
catalog interruption tests complement this drill; they do not convert it into a
managed-storage qualification. See the
[storage decision](../../adr/0054-preserve-coupled-local-container-state.md).
