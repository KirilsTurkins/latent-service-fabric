# PR #974: bounded command-floor release

This reconciliation retains snapshot `d24ff1ac37c52d1d611235033bdd345ae7551d76`
against the current canonical state startup, recovery-worker, namespace, tenant
accounting and command/effect owners. Issue #707's body and comments were
refreshed on 12 October 2026. This is a scoped maintenance delivery, not closure
of #707, #718 or the complete Phase 4 gate.

## Behavior and authority

`state release-expired-command-floor` releases one already expired,
terminalized and purged command identity in an explicitly retired namespace.
It requires current authenticated management permission, the original command
ID, the exact canonical 67-byte namespace/history view, the captured policy
digest and an explicit reason/operation ID. Quiescing, ordinary expiry,
deployment deletion and receipt inspection do not initiate this mutation.
Live original storage readers, retained dependencies, stale history/policy and
wrong scope refuse publication. No automatic retry or precondition refresh is
added.

The existing recovery storage worker carries the original prepaid request and
work reservation through physical completion and retained output. One
caller-driven maintenance owner belongs to the existing state kernel; it adds
no worker, timer or application scheduler. Its fixed resident shell fits the
existing startup/installation metadata reservations, while actual maintenance
pages, plans and I/O use the original 8 MiB recovery-work admission.

The clock projection reads the same protected command/effect clock and uses a
single process boot identity. Its monotonic origin comes from an accepted
protected sample. It creates no persisted maintenance anchor, coverage,
permission or substitute wall clock. Actual covered-lease loss keeps later
maintenance samples denied. Durable progress still enforces its explicit
authorized anchoring and elapsed/drift rules across restart or restored history.

The immutable bounded receipt shares the original native atomic batch and
tenant accounting. Recovery preserves its actor, namespace, command, policy,
view, operation and original completion time, while requiring current
inspection permission. CLI recovery metadata retains the original command and
authorization publication alongside those preconditions.

## Actual checks and retained failures

Four native floor controls passed using the real protected storage worker,
PolicyStore and durable audit owner: actual release/replay/reopen, current
permission after a retained response, wrong-namespace lookup denial, and live
physical-reader/stale-view/policy refusal. Reopen validates linked native rows
and recovers the exact original receipt. The initial reopen failure is retained:
the test registered a maintenance resume decoder for an unrelated namespace
receipt. Only that fixture registration now checks the exact family/prefix;
owned-row codecs and production corruption checks remain unchanged.

Two actual protected-kernel controls passed for coherent original clock samples,
the shared process identity and refusal after covered lease loss. The original
failed concurrent fixture observation remains preserved; the controlled clock
advances coherently after the shared origin is installed.

Broader checks passed: 158 CLI cases, 31 RPC cases, and 192 wire cases with all
26 original ignored cases unchanged. The restored CLI case first failed because
recovery omitted the original command/publication fields; the assertion was
retained and the actual projection fixed. All 28 CI inventory/fragment/discovery
controls passed on Linux. Their Windows symlink/platform failures are retained
separately.

The existing CI Clippy policy is preserved: normal all-target/all-feature wire
and RPC lint checks retain their diagnostics, and the strict selected
`latent`/`latentd`/`latent-testkit`/`latent-admission` check passes. A broader
experimental warnings-as-errors run fails on pre-existing manifest/generated
RPC diagnostics and is not described as a pass. Formatting and independently
reviewed suite registration preserve every original case and ignore guard.

Local receipts are retained under `target/pr974`, including original merge
stages and private diagnostic failures. Private trace printing is absent from
the delivered source. These native tests do not claim signed guest execution,
all six client/guest SDKs, packaged-runtime approval, hostile multitenant
qualification or complete current hosted CI. The unchanged Phase 4 and Feedback
2 acceptance owners remain authoritative.
