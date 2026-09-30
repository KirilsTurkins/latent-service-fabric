# Wiki migration and removal

The complete documentation site replaces the Wiki. Useful current explanations
have maintained replacements, the 27-topic guide review is accepted, and all
26 mapped entries passed actual live destination checks on 2026-09-27.
The [cutover review](wiki-cutover-review.md) links the exact public evidence.
The Wiki and its publishers were already disabled and have been rechecked;
their actual retirement dates remain in the
[September 26 observation](../evidence/wiki-retirement-2026-09-26.json).

Old Wiki URLs, anchors, page bodies and archive notices are not a compatibility
contract. The maintainer's September 22 decision supersedes the original
preservation plan. Git history retains attribution without a second active
documentation service.

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

## Completed cutover and bounded rollback

The reviewed complete site passed protected publication and browser validation.
Every maintained replacement route is live, repository/public entry links use
the site, and the Wiki and both old writers remain disabled. The
[collective decision](../phase-3-gate-review.md) consumes these content and site
prerequisites; #356's final administrative recheck follows that decision.
Source retirement and settings changes retain their actual earlier dates.

If the website later needs recovery, use the [protected publication procedure](website-publication.md)
with a previously published complete artifact and the exact currently live
source. Recheck live routes and retain the new publication receipt. Do not
restore Wiki publishing, move runtime tags or rewrite historical measurements.
Future prose belongs in `docs/`; presentation and publication belong to the
website owner. The retired writers must not recreate a second public site.
