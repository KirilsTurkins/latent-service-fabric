# Command completion coordinator

The shared runtime uses the existing `NativeTransactionAdmission`, activation
manager, protected store, namespace/policy owners and atomic command ledger.
It validates the selected publication, authenticated scope and original
admission budget before native lookup or durable claim publication. Retained
native capacity stays attached to actual accepted work. Descriptive input
cannot grant access or assert durable completion.

The durable claim retains its original sealed namespace expectation. Current
namespace/history and global recovery readiness remain mandatory. Existing
command identities take the authorized recovery path without another guest;
historical caller or grant metadata cannot renew result-read authority.

After actual guest teardown, the lifecycle finalizes original consumption and
invokes the same admission owner's completion with `TransactionCommitControl`.
`CommandCompletion` checks the original claim, role, host, activation, budget and
retained authority before one complete atomic envelope can reach the writer.

The existing final writer fence linearizes cancellation against irreversible
acceptance. Acceptance is not a published terminal outcome. Cancellation while
that I/O is accepted returns `Unavailable` with the closed
`activation.command-commit-acceptance-observed` detail, retaining the original
writer, registration, budget and recovery identity. It cannot report a proposed
success as `AlreadyTerminal` or refund physical work. After actual terminal
publication, cancellation reports the actual state, including platform failure
when disposition remains uncertain. Recovery uses current-authorized lookup.

Original publication, input/preconditions, source/time, namespace version and
history tokens remain bound to the envelope. Current accounted and legacy
format profiles retain their explicit supported decoders and retention metadata;
no reader reconstructs omitted history from current business state.

Durable disposition and delivery/cleanup remain separate. Current result-read
authority is checked before releasing receipt/body data; revocation cannot erase
internal durability or grant a public body. Original producer diagnostics remain
separate from HTTP validation or observation.

Technical abort requires the lower owner's positive private retirement proof and
fresh distinct read/control authorization, not a timeout, notification, dropped
waiter or decoded row. Missing continuity, permission, physical retirement or a
known durable result leaves the original attempt pending/recovery-required.
Physical guards remain in accepted work after observer detachment. Panics after
worker entry quarantine rather than refund occupied memory or infer noncommit.

Duplicates perform fresh authorized lookup before attaching to the existing
bounded registry. Every wake reloads durable state and current permission. A
waiter's own cancellation or deadline detaches delivery only. Missing owner,
interrupted native work, lost delivery and commit uncertainty never schedule a
replacement guest. Explicit protected retry/recovery policy remains a separate
owner operation.

The [PR #811 reconciliation](https://github.com/KirilsTurkins/latent-service-fabric/blob/200c17c26b24d6bf06d8d28102362ea714c1f4eb/docs/development/phase4-handoffs/2026-10-11/pr811-reconciliation.md)
records current validation and snapshot decisions. Installed direct/RPC/HTTP
command, cancellation, crash/restart and the six-guest matrix remain with #388
and its consumers; source or external-client qualification does not finish them.
