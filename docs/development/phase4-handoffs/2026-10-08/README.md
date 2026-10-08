# Phase 4 cleanup handoff - 8 October 2026

Implementation was stopped at the user's request. This branch preserves the current progress before deletion of local worktrees and validation caches. It is a handoff, not Phase 4 completion or release qualification.

The live milestone audit has 32 issues: 7 closed and 25 open. Completed issues are #380, #381, #382, #383, #384, #385 and #393. The remaining acceptance boundaries are recorded in acceptance-audit.json and in issue comments. Earlier merged substrate code does not establish installed workflows, signed guest/client execution, distribution upgrades, measurements or gate #407.

Current remote PR heads and their exact check URLs are in pull-requests.json. PR #825 is already merged (74f84755); #391 remains open because installed startup, ordering, retained-format and recovery acceptance is still pending. Some branches passed CI before acquiring new development conflicts; others have test/provider/security failures. Do not merge a changed functional head using a different head's CI. The user-authorized exception covers only a previously fully passing head followed by a reviewed simple JSON conflict resolution.

All source worktree heads are preserved under checkpoint/phase4-cleanup-20261008 branches. Older no-checkout worktrees report mass missing files; these are not source deletions. Other milestone sessions' dirty worktrees were not edited. Restore checkpoint branches, not a stale local feature branch, when resuming.

## Qualification and outstanding work

The shared deferred HTTP repair c7663996 passed actual Linux all-target checks, the exact 167-case capability list, all 167 capability cases, all 59 HTTP/TLS cases, 250 ControlStore cases plus one original ignore, and ordinary Clippy. It is applied to all eleven current Phase 4 PRs with each branch's additional cases preserved.

The current client PR passed actual native CLI/packaging/policy builds, all Rust SDK tests and Clippy, in addition to source generation and TypeScript semantic/network checks. This does not qualify six separate-node transaction client workflows.

Later installed management, typed command/query/recovery RPC, current control/effect authority and six Java compiler integrations are recorded in integration-v12-current-origin-and-delivery-handoff-v19.md. The latest real signed-node collector still needs qualification: an original HTTP query was refused before journal admission, the loopback Origin policy fixture was corrected without changing authority or success/refusal assertions, and the corrected actual node campaign remains pending. Do not describe these source fixes as a passing installed six-language scenario.

The latest #808 restore and codec work is described in entity-contract-v79-current-restore-and808-handoff-20261008.md. Current published #808 additionally contains actual SDK descriptor/lock/count repairs and its exact source campaign passed 253 tests. Its full current State/recovery execution remains pending; the current hosted Rust job is failing. Older same-operation restore-receipt checkpoints and tests remain preserved as inputs, not a replacement for current qualification.

Current #823's witness fixture has actual source-bound Java host qualification: 78 semantic/lifetime cases, 61 successful protobuf vectors plus the original contradictory case, twelve TCP/protocol suites and captured Java toolchain checks. This is external Java SDK evidence, not signed Java guest/node qualification. The current head and check states are recorded separately; current #823 hosted Rust tests/provider fail.

The retained Go SDK campaign on exact 8785fadf passed all ten actual runtime cases with original components and budgets. Later source repairs and current-head native/SDK results are preserved in agent handoffs. Do not substitute old component evidence for a changed source/profile or skip failed attempts.

The evidence directory contains exact receipts and raw-log identities. Full local toolchains, target caches, raw source archives and unsigned test setup are disposable and are not qualification artifacts. No incomplete campaign is recorded as passed.

## Preserved interrupted work

The older dedup worktree had an unfinished merge. Its exact stage 1/2/3 blobs, working conflict markers, index and binary diff are preserved under conflict-custody; no conflicts were resolved during the stop request. Three genuine historical native-currentness edits were committed as WIP and remain explicitly unqualified. Current agent inventories and checkpoint refs distinguish active work from obsolete validation copies.
