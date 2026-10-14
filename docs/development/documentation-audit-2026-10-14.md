# Post-alpha.5 documentation audit

Audited on 14 October 2026. The published alpha.5 commit is
`f6d8f32177208b60a68f14070f549f927052dd48`; its tree is identical to development
source `a7b5d208` (PR #720). The release promotion used separate squash ancestry,
so a raw `0.1.0-alpha.5..development` log incorrectly includes older phases.
The audit instead follows the 127 merged development PRs after the matching
source tree, through `90cf1f4c87ca24e9a64b077dc2eb501dcef22441`.

The documentation branch starts at PR #970 head
`1e9fa9cdfa02e2a1e8098d2325908cc460fa2de2`, which contains that development tip.
Its additional source commits are pending PR work, not merged post-release
features. Current installed recovery is described with its outstanding native
terminal/pending and packaged acceptance. No runtime release, deployment or
issue closure is part of this documentation change.

[The complete inventory](documentation-audit/2026-10-14.json) records every merged
PR's number, title, merge commit, merge time, changed documentation paths, source
areas and documentation disposition. A documentation path proves a file changed,
not that its instructions were executed or its feature qualified.

## Findings and guide ownership

| Merged area and representative PRs | Finding and maintained documentation |
| --- | --- |
| Dependency capture and trust: #751, #754, #756, #769, #778, #783, #793, #824, #843 | Separate language references existed, but the entry path and catalogue did not expose the six workflows. [Application libraries](../how-to/add-application-libraries.md) now connects declaration, fresh candidate, exact review, trust, offline build and update/watch boundaries. |
| Compatibility/resources: #749, #761, #809, #822, #856 | Package capture was easy to confuse with runtime support. The library guide links actual final import inspection; [packaged resources](../component-development/packaged-resources.md) now names the focused signed .NET lookup evidence while preserving Java's open lookup boundary. |
| Generators/processors: #842, #843, #935 | The Java generator page stopped at generic launchers. It now documents explicit processor selection, unapproved-build request retention, exact approval and normal proc-disabled compilation. C, Go, TypeScript and Rust/.NET executable-input recipes are reachable from the shared guide. |
| Java server and HTTP composition: #748, #762, #771, #776, #785, #819, #895 | The Java server introduction still described lifecycle/max-body work as pending despite later finite signed successes. It now links the current 52-ingress/12-lifecycle source-bound suite and keeps earlier failed evidence as historical pointers. Server profiles are visible in Reference and the catalogue. |
| Preparation and diagnostics: #768, #786, #788, #815, #817, #825, #852 | Reference contracts existed without a task sequence. [Composition inspection](../how-to/inspect-a-composition.md) connects doctor, structural/live preflight, exact target preparation and retained activation diagnostics without equating them with execution. |
| Activation runtimes and streams: #747, #750, #759, #775, #781, #798, #804, #805, #807, #810, #826, #902, #912, #923, #856 | Runtime evidence is finite and language-specific. The changes guide and roadmap link the current records and preserve the gaps in standard threads/executors, ordinary clients, cancellation/exhaustion and installed distributions. |
| State/store/commit: #765–#767, #770, #774, #779, #782, #787, #790, #796, #808, #811, #974 | The roadmap repeated older completed phases while giving the new implementation only a ticket plan. It now maps merged store, authority, sessions, envelopes, completion, retention and restore owners to their maintained contracts; gate #407 remains distinct. |
| Dispatch and external work: #757, #763, #780, #794, #797, #821, #828 | The installed RPC page deferred already merged HTTP integration. It now points to current shared HTTP/deferred installation. [Recovery operations](../operations/transaction-recovery.md) distinguishes durable command disposition, effect inspection, operator plans and provider acknowledgement. |
| Clients and stateful reference: #784, #800, #802, #803, #823, #956, #958, #968 | Six transport facades and authored guests do not imply the complete real-node/client/browser matrix. The recovery guide preserves original selectors and uncertainty; the source transition guide makes explicit profiles and node authority discoverable. |
| Static web delivery: #753, #758 | Existing references correctly cover signed navigation-only 404s and capture-budget diagnostics. They are now linked from the post-release task guide rather than copied into another walkthrough. |
| Contributor workflow: #730, #733, #752, #818, #820, #791, #850, #852 | The local runner, deterministic ownership, bounded external maintenance and currentness contracts remain authoritative. Entry guides link them; dated handoffs move to engineering-record navigation. |
| Dependencies, security and CI | Exact pins and reviewed inventories are the authorities. The audit removes obsolete website README commands and duplicate derivation prose, links one maintained installation sequence and preserves all existing checks, security constraints and opt-in workload limits. |
| Publication: #722, #724, #725 | Frozen alpha.5/alpha.4/alpha.3 snapshots and their recorded source identities remain unchanged. Current guides clearly separate downloaded alpha.5 behavior from newer Development source. |

PRs #750, #780, #818, #833, #846 and #895 had no documentation-path change in
their merge commit. Their changed behavior was checked against existing runtime,
storage, compiler-deadline, snapshot-limit and signing contracts; the current
guides above cover the missing task entry points and outdated Java acceptance
summary. Routine pin/CI changes are included in the complete inventory rather
than expanded into repeated feature histories.

## Removed redundancy

- The roadmap keeps phase boundaries and acceptance links instead of duplicating
  the completed Phase 0–3 implementation and measurement inventories.
- The superseded September 7 feature audit and September 23 orphan-code audit
  pages are removed. [Engineering records](engineering-records.md) points to their
  original PRs and the later completion records.
- Current .NET and Java guides summarize old attempts by linking their original
  receipts. Failed evidence, original hashes and broader acceptance limitations
  remain intact.
- The website README routes installation to one maintained guide instead of
  copying its security/toolchain instructions and stale foundation review status.
- Dated snapshot, SDK, Java/Rust/TypeScript and Phase 4 reconciliations remain
  published records. Their entries no longer crowd the contributor setup sidebar.

## Acceptance limits

This audit validates documentation, navigation and website behavior. It does not
reexecute language compilers, signed guest campaigns, storage migration, provider
qualification or packaged host schedules. Gate #407, SDK epic #677 and the broader
Java/HTTP tickets retain their own acceptance requirements. The source-bound
receipts referenced by a guide keep their original environment and revisions.
New catalogue entries do not change the reviewed guide-coverage matrix or its
execution approvals. Heavy scale/profiling/soak work is not selected.
