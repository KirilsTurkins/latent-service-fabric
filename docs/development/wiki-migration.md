# Wiki migration and removal

The documentation site replaces the Wiki. Migrate useful current explanations,
complete the essential guide reviews and verify the deployed site. Once Phase 3
is complete and that site is deployed, remove the public Wiki and retire its
publisher. Old Wiki URLs, anchors, page bodies and archive notices are not a
compatibility contract. This policy supersedes the original preservation plan
for #356, following the maintainer decision of September 22, 2026.

The [cutover review](wiki-cutover-review.md) records the content map, historical
live route checks and remaining execution steps. Wiki removal is still pending;
the existing inventory does not establish that the final site has been deployed.

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
historical source-link check. To compare against the retained actual Wiki Git repository,
add `--wiki-git PATH`. The optional comparison reads every inventoried blob and
rejects any added, missing or changed file. It does not fetch or publish anything.

The inventory checker resolves old links against pinned source references for
attribution. It does not provide Wiki redirects or require live legacy pages.
The tests cover encoded names, asset references, unknown pages, case collisions
and traversal. Current product-site links use the repository link policy for
root and project base paths and must resolve to maintained content.

## Cutover and bounded rollback

1. Finish protected publication under #355, record the exact source/run/attempt
   and test real representative Pages routes, assets, search and version notices.
2. Complete essential guide review under #345. Record the approved source and
   execution receipts. Site publication alone is not runtime release or Phase 3
   certification.
3. Verify every maintained replacement route and switch repository/public entry
   links to the tested site. Remove obsolete Wiki-specific navigation and active
   content. Record the live deployment identity and content dispositions.
4. Complete the Phase 3 gate. Content migration, guide review and successful
   site publication are gate prerequisites; the final Wiki removal follows this
   decision so that the ordering does not make the gate depend on itself.
5. Retire the old publishing workflow through a reviewed change on its source,
   disable the repository Wiki, and verify that no active writer can recreate
   it. Record the settings/workflow result and close #356. No notice-only Wiki
   publication, redirect layer or indefinitely archived public Wiki is required.

If a destination check fails before removal, finish the site correction before
cutover. If the deployed site later needs rollback, use its protected exact
artifact flow. Do not restore the Wiki as a maintained documentation service or
rewrite runtime tags, release evidence or old benchmark reports. Existing Git
history and pinned receipts provide attribution without a second public site.
Future prose belongs in `docs/`; website presentation and publication belong to
the website owner. The retired Wiki writer must not resume synchronization.
