# PR #808 schema and recovery reconciliation

## Owning issues and comment review

PR #808 implements the storage/recovery portion of
[#398](https://github.com/KirilsTurkins/latent-service-fabric/issues/398) and
[#399](https://github.com/KirilsTurkins/latent-service-fabric/issues/399).
It closes neither issue. Their comments require current full State execution,
installed compatible/incompatible upgrades, signed-node backup/restore-paused
reconciliation and explicit production operator authority. This handoff keeps
those boundaries separate from internal storage and client qualification.

The review includes both complete issues and their comments, plus dependency
comments on #379, #382, #387, #391, #395, #396, #397, #400 and #408.
The closed #382 contract ticket supplies the existing six-guest/six-client
definitions. The remaining tickets retain their installed command, dispatcher,
inbox, payload, retention, management and query acceptance criteria.
The October 8 cleanup stop is superseded by the request to finish this PR.

The original branch head is `9d9f1f3586e203d16733a05782a1785b6c7b7789`.
The normal merge incorporates development
`0211e3126e10f2badbc40f4a85a52beae908709e`, including current native startup
prepayment, retention/recovery partitions, physical retirement, Java futures,
SDK models and exact CI inventories. No existing protocol field or enum is
removed, and historical native receipts retain their original source heads.

## Snapshot decisions

[#957](https://github.com/KirilsTurkins/latent-service-fabric/pull/957) contains
the distinct abandoned restore-receipt reader test at `6a7bfa58`. Its two-file
test patch is reconciled into the current receipt implementation. The accepted
reader retains real source/staged views, original snapshot custody and capacity
until native retirement; dropping the waiter cannot release or reimport them.
Its earlier receipt integration `e9014ee1` is already in the original #808 head.

#972 preserves the bounded HTTP handshake helper refactor already in #808.
#973 is an older integration/CI checkpoint; current development supplies its
superseding contracts and ownership repairs. #966 confirms the distinct #957
continuation and remaining State/installed restore gates. #959 and #978 retain
historical integration/source receipts; they add no independent restore
implementation to this PR. The installed RPC/HTTP workflows in #823/#828 and
the separate signed query/recovery continuation in #879 retain their owners.

## Final implementation and repairs

The bounded migration and restore APIs preserve schema, namespace/incarnation,
command/result/inbox/effect history, original payload/format references and
sealed receipt identity. V1 and V2 recovery profiles keep their separate codecs,
progress bounds and unsupported-decoder refusals. Partial or uncertain staging
remains an explicit refusal; receipt recovery cannot activate a restored root
or replay import. Adoption and resume retain explicit review and currentness.

The recorded [Rust test failure](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/37738332612/job/113198080216)
was a management dispatcher binding assertion against an older constructor
contract. Current development's constructor refusal and independent management
check are retained, with the original global-owner, engine and retirement checks.
Merge reconciliation preserves current prepaid startup/resident memory gates,
reserved recovery workers, single-writer ownership and every existing test.

Normal namespace transitions now reject incomplete migration before preparing
a write. Their final batch also retains the exact original history-row
expectation. Migration staging changes that row, so a transition prepared before
staging fails at the real atomic commit fence. The new race test covers both
legacy and quota-accounted namespaces and verifies unchanged namespace and
original progress after refusal. The restarted incomplete-progress test retains
its original `Unavailable` assertion and passes.

Actual Buf 1.72.0 output proves that the descriptor adds only optional
`NamespaceInspection.policy_digest` string field 12 and its synthetic oneof.
This is a captured policy/binding observation and grants no authority. The
existing namespace-policy field 11 and all prior descriptor semantics remain.
The maintained generators reproduce all six transaction client models, Rust
shapes/conversions, Java bridge and Node descriptor. Actual Grpc.Tools 2.71.0 /
libprotoc 29.0 clean generations produce the updated .NET descriptor lock.

Captured WIT packages keep their original dependency directories and bytes;
the staging helper adds only missing transitive packages. Java clock tests cover
the Java aggregate, forbidden-HTTP and all three schema variants. The separate
Rust result-boundary fixture remains selected only for Rust. Current frontend
capture limits, website/advisory input hashes, CI selection and required run
blocks are preserved rather than replaced with older branch copies.

## Current local evidence

Pinned Rust 1.97.1 Linux passes 356 State cases, including the full migration,
snapshot/restore, receipt/review, paused resume and physical-owner tests.
Commit passes 100; effects passes 138; wire passes 183 ordinary library cases
and 67 service cases. Its 23 existing profile ignores remain. Protected files
passes 25 cases with one existing platform/profile ignore. RPC passes 29 library
and five generated/round-trip cases. These are native library/service fixtures,
not installed signed-node migration or recovery qualification.

The production discovery checker validates all ten relevant Cargo targets and
765 active cases. Exact inventories add 111 State cases and three protected-file
cases, retain every prior case/selection/ignore state, and keep matching minima.

The full Python 3.13.5 Linux suite passes 3,717 cases with the 18 existing
environment guards skipped; the twelve SDK profile controls also pass.
Strict Clippy passes for latent, latentd, latent-testkit and latent-admission.
Changed-package Clippy, workspace formatting, foundation and documentation
checks pass. CI coverage retains 88 baseline and 280 current required run
blocks with 148 delegated script owners.

The retained core memory-accounting and captured-policy observation helpers
also pass their focused package suites: 131 core cases and 149 policy cases,
with the policy suite's seven existing opt-in ignores unchanged.

All six actual client validation paths pass with the regenerated definitions:
Rust's 40 client cases, Go's pinned generation and package tests, TypeScript's
38 transport cases, Java's real pinned generation and bounded TCP/protobuf
suites including 120 transaction checks, .NET's two clean generations and
semantic/transport peers, and the fresh C build's 62 protobuf vectors, ownership
and allocation-fault controls plus all sixteen transaction methods. These
controlled peers preserve original limits and do not qualify installed restore.

## Remaining acceptance boundaries

#398 remains open for the installed compatible/incompatible publication,
canary/rollback and complete retained-format retirement matrix. #399 remains
open for installed signed-node backup, fresh-root activation, paused effect/
inbox review and approved reconciliation after a remote effect succeeded beyond
the backup point. Current publication/grant/provider/result-read authority,
external data-loss acknowledgement and production root authority remain explicit
requirements. No old snapshot can renew a live owner or make old query tokens
current, and no normal code rollback promises business-data or remote-effect
rollback.

Hosted CI is not awaited after push. No merge, ticket closure, installed-node
qualification or refreshed historical receipt is claimed by this delivery.
