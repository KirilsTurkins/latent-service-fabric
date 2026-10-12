# Snapshot pull-request reconciliation

The maintainer authorized review and completion of every open snapshot PR on
12 October 2026, with immediate closure of stale checkpoints. This supersedes
the earlier cleanup stop. The initial live inventory contained 128 snapshot PRs.

[Exact source inventory and disposition](inventory.json) records their public
source heads, incorporating merged PRs and preserved descendant checkpoints.
Branches and historical evidence remain preserved. Closing a duplicate or
superseded checkpoint does not claim completion of its ticket.

Snapshots whose commits occur in an accepted merged PR head are stale source
checkpoints. Earlier checkpoints with newer preserved descendants are reviewed
through those descendants. Independent tips retain their implementation and
qualification requirements until their actual tickets, comments, dependencies,
current source and current-head checks have been reconciled.

The SDK cleanup audit is historical context. Its 357 criteria across 33 issues
are not current acceptance evidence. Current issue bodies and comments govern.
No ticket is marked complete by this inventory.

The [historical handoff manifest](historical-handoffs.json) preserves 837 files
from #850, #959, #960, #966, #975, #976, #977 and #978. It records the original
Git source, each file's exact byte digest, archive member and archive digest.
The archives retain failed and stopped runs, unresolved working copies,
original index custody and source-specific approvals as dated evidence. They
are data for review and recovery. Their relative links and conflict markers
remain inside the archive's original tree.

| Historical source | Preserved archive | Current acceptance owner |
| --- | --- | --- |
| #850 Phase4 cleanup | [Archive](historical/pr850.zip) | #379 and its active leaf tickets |
| #959 integrated Java collector | [Archive](historical/pr959.zip) | #718; source reconciliation continues through #968 |
| #960 SDK cleanup | [Archive](historical/pr960.zip) | #677 and its language/runtime tickets |
| #966 entity/storage preservation | [Archive](historical/pr966.zip) | #394, #397, #398 and #399 |
| #975 preparation diagnostics | [Archive](historical/pr975.zip) | #709 |
| #976 packaged preflight | [Archive](historical/pr976.zip) | #710 |
| #977 dependency/renderer capture | [Archive](historical/pr977.zip) | Current compiler and renderer owners |
| #978 Portable preservation | [Archive](historical/pr978.zip) | #389, #401, #405 and #406 |

Current delivered slices include the manifest boundary correction in #851,
bounded native currentness rechecks in #852, protected stream/parser/peer work
in #912 and rebuilt Rust standard-clock evidence in #902. Their current heads
and hosted checks govern merge eligibility. The historical approvals inside
these archives apply only to their original bytes and source/profile scope.

The pinned secret scanner checked 836 historical/current text files. Its
39 historical bare-hex matches are independently verified Git commit/tree
identities, bound to complete file hashes and exact JSON fields in the
[noncredential review](historical-secret-review.json). No unreviewed finding
remains and no repository exception was added. Archive member and checksum
verification, documentation links and CI command coverage passed.
