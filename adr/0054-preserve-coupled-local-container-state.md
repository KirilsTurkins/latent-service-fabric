# ADR-0054: Preserve coupled local container state under a shared owner fence

- Status: Accepted
- Date: 2026-09-27
- Related: #636, #640

## Context

Publication identity, immutable content links, lifecycle/evidence state, route
selections, receipts, audit and trust configuration form one recovery unit.
Copying a catalog row or testing ordinary file I/O is insufficient. The owner
excluded Azure resources and simulated cloud results, so this delivery qualifies
an actual local persistent deployment alternative and makes no Azure claim.

## Decision

The container entrypoint acquires one protected nonblocking flock on
`<dataDirectory>/.container-owner.lock` before preflight/activation and retains
the descriptor across native exec. Its lifetime is the native container, adding
one node-fixed descriptor and no thread or task. A second owner or maintenance
process fails before it can mutate catalog state. The file is never unlinked to
release ownership. Container PID 1 termination also terminates its namespace's
children; this fence is not a distributed lease or a standalone host supervisor.
Existing native per-catalog locks and format checks remain in force.

Stopped snapshot/restore acquires that same fence and requires all configuration
writers to be quiescent. Operate only on the node-owned `config`, `data`, `cache`
layout and create a fresh disjoint destination. Preserve bytes, modes, ownership
and hard-link groups. Reject symlinks, special files, foreign owners, external
hard links, permissive paths, extended ACLs, changed sources and incomplete
snapshots. Publish a private completion manifest only after exact verification
and file/directory synchronization. Restore never merges or overwrites state.

## Bounds and support

The helper is a finite administrative operation: two minutes, 16,384 entries
and 1 GiB logical bytes. It retains a failed partial copy without a completion
marker. Production installations outside this bound require a reviewed whole
filesystem snapshot under stopped ownership; increasing the bound is explicit.
The reusable helper does not claim online backup or remote filesystem support.

The test observes an actual local ext4/XFS-backed Docker volume, records the
actual type, and tests two signed publications across update/restart/restore and
explicit rollback. Native receipts and unrelated publication identities must
survive. No inferred cloud peer, simulated Azure mount, privileged runtime,
power-loss claim or protocol-name-based NFS/SMB verdict is accepted.
