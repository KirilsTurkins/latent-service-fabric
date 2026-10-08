# Phase 4 cleanup handoff - 8 October 2026

Implementation was stopped at the user's request. This branch preserves the current progress before deletion of local worktrees and validation caches. It is a handoff, not Phase 4 completion or release qualification.

The live milestone audit has 32 issues: 7 closed and 25 open. Completed issues are #380, #381, #382, #383, #384, #385 and #393. The remaining acceptance boundaries are recorded in acceptance-audit.json and in issue comments. Earlier merged substrate code does not establish installed workflows, signed guest/client execution, distribution upgrades, measurements or gate #407.

Current remote PR heads and their exact check URLs are in pull-requests.json. Some branches passed CI before acquiring new development conflicts; others have test/provider/security failures. Do not merge a changed functional head using a different head's CI. The user-authorized exception covers only a previously fully passing head followed by a reviewed simple JSON conflict resolution.

All source worktree heads are preserved under checkpoint/phase4-cleanup-20261008 branches. Older no-checkout worktrees report mass missing files; these are not source deletions. Other milestone sessions' dirty worktrees were not edited. Restore checkpoint branches, not a stale local feature branch, when resuming.

## Qualification and outstanding work

The shared deferred HTTP repair c7663996 passed actual Linux all-target checks, the exact 167-case capability list, all 167 capability cases, all 59 HTTP/TLS cases, 250 ControlStore cases plus one original ignore, and ordinary Clippy. It is applied to all eleven current Phase 4 PRs with each branch's additional cases preserved.

The current client PR passed actual native CLI/packaging/policy builds, all Rust SDK tests and Clippy, in addition to source generation and TypeScript semantic/network checks. This does not qualify six separate-node transaction client workflows.

Installed management and RPC recovery followups have source-qualified checkpoints. Their Native attempts exposed configuration, physical-retirement, response-body, foreign-owner and namespace-history failures. Later repair head 68856c46 preserves original limits and assertions; its actual focused Native qualification remains required. The ordinary typed transaction RPC gateway b31fcdcb has source checks and input preparation only; its native compilation, real command/query/lookup, signed guest provisioning and delivery are pending.

Restore receipt recovery f4ab131b passed all 204 source cases and generation gates; six real protected-root schedules and the full State library remain required. No restored bytes may be reimported or activated by treating a lost response as nonexecution.

The retained Go SDK campaign on exact 8785fadf passed all ten actual runtime cases with original components and budgets. Current later memory/accounting changes need current-head qualification; the earlier intermittent CI failure has not been explained by changing budgets.

The evidence directory contains exact receipts and raw-log identities. Full local toolchains, target caches, raw source archives and unsigned test setup are disposable and are not qualification artifacts. No incomplete campaign is recorded as passed.
