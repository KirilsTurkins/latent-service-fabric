# PR #823 reconciliation

PR: <https://github.com/KirilsTurkins/latent-service-fabric/pull/823>

The original `1417e360` checkpoint is reconciled with development `d056e55a`
through a normal merge. Current State, Effects, Node completion, authenticated
RPC, CLI, SDK and CI owners remain the implementation foundation.

## Issue and snapshot context

Read the bodies and comments of #718, #387, #388, #400, #408, #389 and #401.
#718 owns signed Java guest qualification; #387 owns original command/result
recovery; #388 owns transaction lifetime/completion; #400 owns supported
operator entry points. The query and guest/client matrix requirements remain
separate acceptance surfaces. All these issues remain open. This PR has no
closing reference and closes no ticket.

Snapshot #974's `bd4cb189` implementation is already an ancestor of the original
PR head. It supplies no missing later fix. #962 preserves a conflicted #823
handoff, including 57 unresolved paths, and is historical evidence. #879 retains
the signed Java continuation collector and failed query attempt; it does not
qualify the guest. #828 owns the remaining installed HTTP integration. State
snapshots #972/#973 were already reconciled through #808 on development.

## Delivered behavior

- Configured state targets capture the exact admitted signed companion and
  actual deployment through the existing protected recovery worker. Full
  deployment restrictions are checked against the captured catalog record.
  Unsupported additional state-grant constraints refuse explicitly.
- Native configuration prepays startup, persistent installation metadata and
  a full serving recovery request. Eight targets share each resident lease;
  metadata survives detached workers, selections and response holders.
- The existing transaction RPC adapter is registered on the existing listener.
  Commands and queries retain `NativeTransactionAdmission`, the activation
  manager, Wasmtime and actual cleanup/completion owners. Missing namespaces
  expose authenticated management; an explicit restart after creation captures
  their real lifecycle before transaction readiness.
- `LookupCommand`/`LookupCommit` use the original protected store and reserved
  recovery capacity, derive caller scope and seal current `read-result` policy.
  They preserve original source, fingerprint, payload/rejection, receipt and
  real historical attempt rows without guest execution or automatic retry.
  Pending history supplies no fabricated abort proof.
- Retention, policy deadlines, current publication/policy and actual namespace
  fences remain live through final frames. Receipt lookup uses identity
  retention after body expiry. Actual storage corruption reaches the protected
  owner's failure latch. Read audits finish on the physical worker and are
  acknowledged before publication.
- Startup diagnostics retain bounded producer codes and redact private data.
  The private startup helper uses normal startup/shutdown. Obsolete offline
  restore modes refuse before opening the store.
- Exact CI inventory includes the three native examples and all new cases,
  while retaining previous cases, ignore guards and required command coverage.

## Verification

The current workspace build, workspace Clippy, strict Clippy for the four
maintained application/admission/testkit packages and formatting passed.
The five changed native library suites passed 1,024 ordinary cases. Exact
discovery recognized all 191 targets and 4,113 active cases; discovery does not
claim that all those cases executed. Foundation, documentation and CI command
coverage checks passed, preserving 88 baseline and 280 current required blocks.
Scoped pinned Gitleaks found zero findings and used zero exceptions.
The pinned deferred NATS campaign passed all 9 real cases, including the seven
that failed on the original PR's older merged checkout. The original-result
campaign passed all 26 maintained real Rust guest cases. The signed native
capture case checks real package signatures/provenance, protected startup,
namespace creation, selected target matching and positive physical retirement;
it does not execute or qualify the signed Java application. The full Python
suite passed 3,861 cases with all 18 original environment guards preserved.
The failed first Python run and native fixture attempts remain in local
`target/pr823` evidence; their failures were corrected before delivery.

## Remaining qualification

The standalone slice installs state-only commands, fresh queries and original
result recovery with default host-derived caller scope. Signed deferred HTTP
intent rules/adapters and application HTTP routes remain #828/#409 work. Live
installation replacement and configured delegated/shared recovery bindings
require their explicit current-owner integration.

The preserved Java collector still uses its older version-1 HTTP/offline
configuration and needs porting before a current campaign. Signed Java aggregate
execution, state/intent atomicity, HTTP loss/recovery, crash/retention/restore,
all six guest/client matrices and authenticated clean-host packaged delivery
remain unqualified. Historical receipts and synthetic collector oracles do not
satisfy those gates. CI is queued by the push; delivery does not wait for it.

Operator details: [installed transaction RPCs](../../installed-transaction-rpc.md).
