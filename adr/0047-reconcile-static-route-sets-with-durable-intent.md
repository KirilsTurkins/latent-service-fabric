# ADR-0047: Reconcile static route sets with durable intent

- Status: Accepted
- Context: first integration feedback #641

## Decision

Provide a finite Node.js workflow over the existing operator CLI. A route set
contains one immutable publication and at most eight explicit GET/HEAD pairs.
Planning requires current publication eligibility and a coherent catalog version
across selected route reads. An existing route's identity and configuration must
match; this workflow changes only its target publication and preserves metadata.

Persist the complete plan and each immutable operation ID with its observed
object generation and global state version before dispatch. Each write is a
single native mutation. Only a confirmed state-conflict rejection permits a new
ID and new state precondition, after verifying the original route is unchanged.
Four attempts per route, 64 writes and 256 commands per invocation, 1 MiB local
records/output and a maximum 600-second deadline bound retained work.

On uncertain output, preserve pending intent and stop. Recovery looks up the
exact receipt and independently checks the current route and target eligibility.
An evicted/UNKNOWN receipt never proves non-execution, even if the desired route
is currently visible. The operator must inspect state and create explicit new
intent in another journal. A historical receipt never overwrites a newer route.

## Durability and ownership

Journal writes use a same-directory private temporary file, file sync, atomic
rename and directory sync. A private exclusive lock prevents two local owners.
The journal is bound to endpoint/profile/node/tenant, never a stored credential;
the CLI endpoint and tenant are passed explicitly on every call. Credential
rotation does not change route intent. The native server remains the authority
for authorization, CAS, trust and final publication eligibility.

Run on a local qualified Linux/WSL filesystem; this does not qualify a managed
mount. After process death, only a human or supervisor that establishes owner
termination may remove the exact orphan lock. Pending staging files never replace
the last complete journal. Each CLI child is reaped and its bounded output is
validated before use; diagnostics do not echo stderr or credential configuration.

## Visibility and rollback

Sequential GET then HEAD writes have an observable mixed-publication window.
The result reports complete, partial, failed or uncertain and does not claim
atomic visibility or guaranteed convergence against continual conflicting writers.
A complete result requires a coherent current route snapshot plus live eligibility.
Rollback is another explicit plan with new operation IDs and currently eligible
target evidence. It does not reuse old authority or silently repair foreign edits.

## Verification

Fault-oriented model tests cover interrupted pairs, lost replies, unrelated and
same-route conflicts, receipt eviction, revoked authority, explicit rollback,
bounded retries and immutable intent. Real Linux I/O tests cover private modes,
exclusive owners, symlink rejection and interrupted staging. The signed static-site
CI workflow exercises the real native CLI/node, deliberately discards one actual
successful reply, interleaves an actual unrelated writer and advances 65 actual
operations to evict the pending receipt. These are bounded correctness scenarios,
not simulated managed-host qualification or a load benchmark.
