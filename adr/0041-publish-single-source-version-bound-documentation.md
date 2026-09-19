# ADR-0041: Publish single-source, version-bound documentation

## Status

Proposed for parent review under [#346](https://github.com/KirilsTurkins/latent-service-fabric/issues/346).
The user approved Docusaurus and these ownership boundaries. This record does
not approve a deployment, a completed guide, or a runtime support claim.

## Context and finite scope

[The finite migration gate #345](https://github.com/KirilsTurkins/latent-service-fabric/issues/345)
blocks Phase 3 #201/#240, not the continuing Documentation & Learning milestone.
That milestone remains open without a due date. Its later additions do not
expand the initial gate without explicit review. [#237](https://github.com/KirilsTurkins/latent-service-fabric/issues/237)
owns integrated operator/runbook correctness and delegates shared onboarding to
#357, executable clients to #358, capabilities/security to #359 and Angular to
#361. Neither #237 nor this site requires #345/#240 to close first.

## Authoritative locations

| Material | Owner and location |
| --- | --- |
| Website application, dependencies, plugins and tests | Independent TypeScript/Docusaurus package in `website/`, with its own exact npm lock |
| Current prose | Existing `docs/`; optional reviewed `.mdx` only when interaction is needed |
| Main docs presentation | Exactly one main docs plugin reading `../docs` directly, with Start/Learn/How-to/Reference/Understand/Contribute sidebars |
| Decisions | Existing `adr/`, presented by a separate labelled docs-plugin instance; acceptance of an ADR is not feature availability |
| Runnable sources | Their owning SDK/application/example projects; never replacement implementations inside the website |
| Scenario registration | `examples/guides/`, reserved for #351/#357; registration references full owning sources, not pasted six-language copies |
| Normative contracts | Existing WIT, Protobuf and product schema directories; website JSON schemas govern documentation metadata only |
| Generated local data | `website/.docusaurus`, `.generated`, `build` and `node_modules`, ignored and never source branches' published content |

Markdown paths remain valid in the checkout. No current or historical document,
benchmark payload or evidence byte is moved or rewritten for compilation.
`docs/wiki` is inventoried separately, not bulk-published. #356 owns useful
unique Wiki content, legacy URLs/notices and retirement of the separate writer.

The compiler uses Docusaurus's experimental `markdown.format: 'detect'`: `.md`
is CommonMark/GFM-compatible prose, `.mdx` is executable MDX. The pinned compiler
must build the actual corpus and fixtures, including tables, fences, Unicode,
HTML/details, anchors and diagrams. Experimental support is a tested dependency,
not an assertion of universal GitHub Markdown equivalence. Unsupported syntax
fails with its source location; do not hide warnings by broadly disabling checks.

## Routes and source boundaries

The main plugin publishes current documents below `/docs/`; decisions live below
`/decisions/`. Paths and ADR numbers remain stable; case, ambiguous routes,
missing targets and anchors are validated. The repository-link plugin resolves
relative links against the owning source, never a duplicated prose tree.
Published documents become site routes. SDK/source/WIT/schema/evidence links
become exact commit-pinned repository links, not public copies of those trees.
Existing explicitly historical source identities stay historical.

The resolver rejects escapes beyond the repository, encoded separators, missing
or wrongly cased targets, unsafe schemes and symlinks/reparse escapes. No remote
include, arbitrary source import or signing/credential material is copied by a
Markdown link. Only individually approved, bounded illustrations/downloads are
copied; unapproved ordinary source links remain repository links. Global brand
assets belong to `website/static/brand`; documentation illustrations belong to
the associated content snapshot. Project base path and custom-domain root are
separate tested build configurations, not deployment claims.

## Versions and one publishing authority

The only future Pages writer is a protected, reviewed workflow on
`development`, owned by #355. It builds one site containing an actual released
alpha snapshot plus clearly labelled development material. `release` and tag
workflows may propose snapshot updates but never race as independent writers.
The current bootstrap candidate is the existing `0.1.0-alpha.3` prerelease;
#353 must verify its exact release/source identities before snapshot creation.
Deployment requires protected environment approval, exact reviewed source/run
identity and only the publisher job's necessary Pages/OIDC permissions. PR
builds have no publishing credentials, no privileged PR execution and no writes
to a trusted publication cache.

#353 creates `versioned_docs`, `versioned_sidebars` and `versioned_examples`
together. Each immutable manifest names documentation source commit, exact
runtime/profile compatibility, example source commits/hashes, illustration
hashes, source/edit URL commit and correction provenance. Released snapshots
come from the existing release, never relabelled development. A released page
may read only its registered versioned examples and illustrations: missing
version data fails, never falls back to current SDK code. Global brand changes
are the deliberately separate shared exception. Corrections retain the original
runtime/example identity and record a reviewed correction commit; changed
example semantics require renewed qualification, not just a prose patch.

The foundation publishes only labelled current development locally. Its
`site-manifest` interface records source SHA, dirty state, page and asset hashes
and routes; a dirty build is not publication evidence. Snapshot creation,
released-channel UI and deployment are not implemented by this ADR/foundation.
The initial Phase 3 guide launch can include the existing released alpha before
the future Phase 3 tag exists. That tag and #240 closure are not prerequisites.

## Finite coverage and authoring review

[`website/content/coverage.json`](../website/content/coverage.json) maps the
finite #345 outcomes to actual current pages and owning source/test references,
implementation prerequisites, delegated guide issue, audience, owner and honest
evidence/review state. Its local schema and tests reject absent/duplicate IDs,
unknown sources/pages, invalid paths and inconsistent completion assertions.
New initial required rows require explicit gate review. Existing references
are mapped even when practical teaching work remains pending.
Implementation prerequisites never point back to the guide/runbook owners or
the consuming phase gates; those are review relationships, not dependency cycles.

Each practical guide must contain: reader outcome, supported version/profile,
prerequisite tools and authority, complete example source, copyable commands,
expected observations, meaningful failure cases, cleanup, deeper reference and
actual validation level. Review separately checks retained activation IDs,
uncertainty, cancellation versus completed cleanup, overload and finite resource
ownership where applicable. Reference-only pages and source extraction are not
runnable-guide evidence. Test doubles are not real-node qualification.

The normal coverage check validates truthful structure and references. The
separate acceptance mode rejects pending human reviews or missing execution
evidence; file/page existence cannot promote a row. #237 and the named content
owners supply command walkthroughs and version-bound evidence; the parent reviews
the finite matrix. Automated Markdown compilation does not replace pedagogy,
visual/accessibility review or actual product tests.

## Execution, interfaces and maintenance

Website install/check/test/build commands neither invoke Cargo nor execute SDKs,
start nodes/registries, fetch includes or use deployment credentials. They read
existing content as data. Site configuration, local plugins, dependencies and
MDX are reviewed executable build inputs, not a sandbox for hostile authors.
The repository input index stays in server-only plugin closures: Docusaurus
serializes site configuration into browser code, so private paths and complete
source inventories must never be plugin-option data in that configuration.
Any future snippet extractor (#351) receives an exact version/source manifest,
allowlisted source path and bounded named region, with size/line limits; it
returns display text plus hashes/verification metadata, never execution output
invented by the site. #352 supplies accessible switching/copy controls over that
registry. #349 owns theme tokens; #350 owns maintained illustrations while
preserving historical bytes; #354 consumes page/version metadata for search and
built-site accessibility. These interfaces do not claim those children delivered.

#355 must add narrowly scoped website CI and exact generated-path exclusions,
preserve `CI result`/documentation profiles and existing runtime/frozen-evidence
checks, and integrate the new lock into security inventory. Until then the
existing classifier conservatively selects full CI for unknown website source;
this foundation does not globally exempt it or modify shared CI ownership.

@KirilsTurkins owns the site/dependency upgrade and finite gate review. Future
framework/plugin/tool updates are exact-pin PRs with registry/upstream identity
review, audit, corpus builds, path/MDX fixtures and base-path tests. Content owners
maintain guide walkthroughs; #354's owner maintains search/accessibility; #353
and #355's owners maintain snapshot/publishing and rollback receipts. Ongoing
maintenance continues after the finite gate closes.

## Rejected alternatives

- A root npm workspace would couple website dependencies/commands to SDK and
  Angular qualification; `apps/website` would blur runtime application ownership.
- An independently edited `website/docs` would create competing product prose.
- A wholesale Wiki-branch merge would import stale duplicates and publishing
  machinery rather than perform #356's reviewed migration.
- Copying repository roots would publish private fixtures/signing material and
  unbounded benchmark archives. Links are not authority to copy them.
- A manually maintained six-language paste library would drift from owning
  sources and conceal language-specific lifetime and transport contracts.

## References

- [Existing CI profiles](../docs/development/ci-profiles.md), [SVG convention](../docs/svg-style.md), [SDK boundary](../sdk/README.md).
- [Docusaurus docs plugin](https://docusaurus.io/docs/api/plugins/@docusaurus/plugin-content-docs), [Markdown modes](https://docusaurus.io/docs/markdown-features), [versioning](https://docusaurus.io/docs/versioning), [deployment](https://docusaurus.io/docs/deployment).
