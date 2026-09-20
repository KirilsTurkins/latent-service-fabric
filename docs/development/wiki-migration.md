# Wiki migration and publication continuity

The source inventory and migration work are ready for review. Public cutover is
pending a successful protected Pages publication and the reviewed essential
guides. Existing Wiki entries remain available during that transition.

## Preserved source and published identities

The complete [inventory](../evidence/wiki-migration-2026-09-20.json) records all
26 Markdown pages, four assets and the live publication manifest. It also records
the source home/sidebar/footer, diagram generator, validation/dependency files,
old publishing workflow and publication receipt. Every published page and asset
matches the reviewed source byte for byte; the live manifest is the only extra
file. The source branch and live Wiki were inspected independently.

- Source: `d1035a50d2fd99b076c74dd958ca4437d909f2ec` on `docs/wiki`.
- Actual Wiki: `e0cc50fe654b783f189b30a8a6f7946d66177180`.
- Publisher source: `3898dbd0970559a566990920ca9172db580f990e`.
- [Original successful publication](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/34768891141).

A verified Git bundle preserves the complete published history in the local run
receipts. Its exact byte count and SHA-256 are in the inventory. Every original
page and asset also has a pinned product-repository source reference, so review
does not depend on the currently visible Wiki or a mutable branch name.

## Content ownership and migration map

Each inventory entry names its destination and disposition. Current explanations
reuse the product documentation. The useful identity definitions and recovery
distinctions were selectively moved to [runtime identities](../learn/runtime-identities.md)
with source attribution. The old FAQ's alpha.3-only SDK and future-phase claims
are preserved in its historical source, without presenting them as development
capabilities. No older product code is merged from the Wiki branch.

Phase 0/1 reports, infrastructure comparison numbers and all four generated
visuals remain historical. Their original source references and identities stay
pinned. Current runtime diagrams remain owned by the documented product sources;
a palette change must not silently rewrite historical evidence.

Run `python tools/wiki_migration.py` for the bounded offline map, destination and
legacy-link check. To compare against the retained actual Wiki Git repository,
add `--wiki-git PATH`. The optional comparison reads every inventoried blob and
rejects any added, missing or changed file. It does not fetch or publish anything.

Wiki links and encoded names are resolved case-sensitively. Existing fragments
continue to address their preserved original pages. A migration notice links to
the new guide separately, instead of guessing that a renamed guide has the same
heading. The tests cover aliases, encoded names, asset references, unknown pages,
case collisions and traversal. Product-site links keep the existing repository
link policy for root and project base paths.

## Cutover and bounded rollback

1. Finish protected publication under #355, record the exact source/run/attempt
   and test real representative Pages routes, assets, search and version notices.
2. Complete essential guide review under #345. Record the approved source and
   execution receipts. Site publication alone is not runtime release or Phase 3
   certification.
3. Prepare a focused PR against `docs/wiki`: retain page bodies/assets, prepend
   a prominent archive notice with each mapped replacement, and update Home,
   `_Sidebar` and `_Footer`. GitHub Wiki URLs cannot be redirected by Pages.
4. Publish those reviewed notices through the existing Wiki owner, then disable
   its old active writer in a separate reviewed change. Retain the source,
   generator and before/after publication receipts. Update repository entry links
   to the tested Pages URL in the same reviewed cutover.
5. Re-inventory the actual Wiki and verify each replacement. Record publication
   identities and live checks; close #356 only after the cutover is demonstrated.

If the new site is unavailable, keep or restore the retained Wiki entry notices
to their prior reviewed state and roll Pages back through its protected exact
artifact flow. Do not rewrite runtime tags, release evidence or old benchmark
reports. Future documentation prose belongs in `docs/`; website presentation and
publication belong to the website owner. The retired Wiki writer must not resume
normal content synchronization.
