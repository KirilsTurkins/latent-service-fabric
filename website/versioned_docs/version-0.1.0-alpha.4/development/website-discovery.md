# Maintain documentation discovery and local search

The website offers Start, Learn, How-to, Reference, Understand and Contribute
entry points plus a [task catalogue](../../website/src/pages/guides.tsx). The
catalogue uses the existing `website/content/coverage.json` rows and published
pages. It does not create new guide acceptance claims: a reference remains
labelled as a reference until its owner supplies a reviewed walkthrough.

## Search ownership and scope

LSF maintains the small Docusaurus integration in
`website/src/theme/SearchBar/`, `website/src/pages/search.tsx` and
`website/lib/search-build.mjs`. The reviewed engine is
[MiniSearch 7.2.0](https://github.com/lucaong/minisearch/tree/3d239d1c3ae7aef1bf5d8945dd7b5f0709f646f5),
a browser/Node JavaScript library with no runtime dependencies. The website lock
pins its registry integrity. This is an LSF-owned local integration, not an
official Docusaurus search service. The website maintainer owns updates and
advisory review; consult the upstream
[Docusaurus search options](https://docusaurus.io/docs/search) when changing it.

The production build indexes the rendered Markdown/MDX content of the explicit
public documentation and decision inventory. It retains headings, section
anchors and all published language-tab text. Navigation, scripts, styles and
pages with a `noindex` robots directive are excluded. Hidden source files,
unreferenced snippet regions, Wiki trees, component review pages and test-only
build directories are never added to the corpus. An archived page can remain
readable while opting out of search using Docusaurus `noIndex: true` front matter.

The index is limited to 6,000 records and 8 MiB. Individual rendered sections are
limited to 256 KiB and split into 6,000-character search records without dropping
their remaining text. Exceeding these limits fails the build and requires review.
The maintained build check recomputes the expected index from the actual HTML
and publication identity, rejecting altered or stale content. Browser loading
also checks the revision, base path, channel inventory and byte limit.

Queries execute in the reader's browser. Only the static same-origin index is
downloaded; there is no search backend, third-party query collection, account or
secret. Query URLs use `search/?q=publication&version=0.1.0-alpha.3`. Results are
restricted to that selected channel and labelled with its version and profile.
Unknown versions and empty results have explicit recovery states. The navbar
preserves the selected documentation channel; optional local storage failure
does not prevent a version-labelled URL from working.

## Add or revise a discoverable guide

1. Add current prose under `docs/`, following the existing coverage contract and
   [authoring ownership](website.md). Use registered source examples instead of
   copied SDK programs.
2. Update the relevant coverage row's page path and role. Audience, SDK language
   and topic filters only expose values backed by existing catalogue entries.
   Catalogue filters have stable `audience`, `language` and `topic` query fields.
3. Keep each heading meaningful: search results link directly to its rendered
   anchor. Preserve historical snapshot bytes; follow the
   [version procedure](website-versions.md) for attributable corrections.
4. Extend the existing journey in `website/scripts/test-discovery.mjs` if the new
   guide changes a reader task. Reuse the ordinary website workflow and compact
   receipts; do not add a separate benchmark or issue-numbered workflow.

## Verification

Run website type/unit checks, both production builds, `test:build`,
`test:examples`, `test:versions` and `test:discovery` after committing the source.
The discovery journey uses the pinned Playwright browser and
`@axe-core/playwright` 4.13.0. It fails on serious/critical WCAG A/AA findings,
incorrect-version results, broken required targets, external browser requests,
hydration errors and failed navigation. It covers landing-to-guide, query URLs,
released search, no results, missing versions, filters, previous/next links,
direct reload, light/dark, keyboard, mobile and reduced motion. The theme suite
and manual review supplement automated accessibility checks; a 640 CSS-pixel
reflow check alone is not a claim of native browser zoom verification.

Review the actual production pages manually for sensible task wording, reading
order, visible keyboard focus, native 200% browser zoom and diagram readability.
Retain only screenshots that show a useful review state. Compact automated
receipts go to `website/.generated/discovery-review/`. These checks qualify site
behavior; runtime and SDK execution evidence retain their original owners.
