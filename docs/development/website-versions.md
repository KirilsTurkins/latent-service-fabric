# Documentation publication identities

Released guides use an immutable documentation snapshot. Development continues
to read `docs/` and is labelled separately from released snapshots. The version menu
selects the historical page where that page exists. A missing historical page
has no development content substituted at its URL.

The initial release channel is `0.1.0-alpha.3`, from commit
`44891f4158a663de5c08b177431686ec70c0bdf3`. Its 80 documentation pages and five
approved illustrations come from that commit. It has no registered multilingual
example bundle: the existing inline material remains historical prose. This
snapshot does not advertise the later native installer, Angular workflow or
six external Phase 3 clients as released alpha.3 features.

## Identity and ownership

The current [example registry](../../examples/guides/registry.json) and
[extraction contract](website-examples.md) remain source-owned. A snapshot owns
separate identities for:

| Field | Meaning |
| --- | --- |
| `runtimeVersion`, `runtimeSource` | The runtime release to which the guide applies and its exact commit. |
| `documentationSource` | The exact commit supplying prose and referenced documentation. |
| `exampleSource` | The exact commit supplying registered implementation and validation source. |
| `snapshotIdentity` | SHA-256 of the deterministic manifest, including document, asset, example and navigation identities. |

`website/versioned_docs/version-<version>/` and
`website/versioned_sidebars/version-<version>-sidebars.json` use the conventional
[Docusaurus versioning layout](https://docusaurus.io/docs/versioning).
`website/versions.json` is the publication inventory. Matching `versioned_examples`,
`versioned_assets` and `versioned_manifests` bind the additional LSF data. These
are historical publication inputs, not another independently maintained current
documentation tree. The built `site-manifest.json` records compact publication
identities alongside the development source and base path.

The documentation support notice identifies the selected profile and exact
source. Example verification retains its original source-extraction, local-test
or real-node scope. Rendering, timestamps and labels do not create runtime
evidence, a stable-release promise or hardware-independent performance claims.

## Create a reviewed snapshot

Use the pinned website toolchain and already available local commits. Verify the
runtime tag against its published release separately; the command does not fetch
refs, create tags, execute SDKs or publish a runtime. For the bootstrap snapshot,
run from the repository root:

```sh
npm --prefix website run snapshot -- \
  --version 0.1.0-alpha.3 \
  --runtimeVersion 0.1.0-alpha.3 \
  --runtimeSource 44891f4158a663de5c08b177431686ec70c0bdf3 \
  --documentationSource 44891f4158a663de5c08b177431686ec70c0bdf3 \
  --exampleSource 44891f4158a663de5c08b177431686ec70c0bdf3 \
  --profile phase-2
```

All source arguments must be complete commit identities. Only public documentation,
explicit registered examples and individually approved assets are copied. Referenced
code remains an exact-commit source link. Git symlinks, missing regions, mismatched
source identities, active SVGs and changed copied data fail validation. Versioned
example resolution never imports the development SDK tree.

The finite limits are three maintained snapshots, 20,000 inventoried repository
paths, 2,000 documents, 100 approved assets and 32 MiB of snapshot input/output.
Individual documents are bounded to 2 MiB, SVGs to 64 KiB, and example extraction
retains its smaller file, region and total limits. No benchmark archives,
dependency directories, credentials or runtime state are copied to the site.

Generation stages deterministic files under `.generated/version-staging` before
installing immutable destinations. `versions.json` is replaced last. An
interrupted run can resume only with identical bytes; a collision fails instead
of overwriting an existing snapshot. Review the new files and manifest in a PR,
then run types, snapshot/unit tests and both production builds with their browser
checks. Unregistered extra historical pages are rejected too.

## Corrections and retirement

A correction for an existing runtime uses a new documentation snapshot identity,
such as `0.1.0-alpha.3-docs.2`, with the same `runtimeVersion` and `runtimeSource`.
Create the correction from the appropriate historical documentation source;
review it for accidental claims about unshipped features. Keep `exampleSource`
at the original implementation unless an explicitly reviewed example correction
is needed. Changed instructions must match `documentationSource`. Do not edit
signed release, benchmark or prior test receipts to make them match newer prose.

Maintain the newest and previous runtime documentation, with one additional
slot for an attributable correction. Retiring a channel is an explicit PR that
updates the inventory and removes that complete snapshot's files together.
History remains in Git. A missing retained version must fail the build rather
than quietly use development. Future snapshot upkeep belongs to the continuous
documentation milestone; Phase 3 does not require a future Phase 3 release tag.

## Validation and complete-site rollback

The prose validator checks historical registration, exact bytes and fences.
The mandatory site job checks historical links against their own repository
inventory, assets, source identities, example bundles, routes and browser output.
Current prose still receives ordinary repository-relative link validation.

The snapshot tests use two deliberately different versions, changed assets,
partial language availability, documentation corrections, linked sources,
missing regions, altered copies and interrupted publication. Synthetic examples
remain labelled as rendering fixtures and provide no SDK qualification.

After committing the reviewed sources, install the separately locked package
manager with `npm ci --prefix website/toolchain --ignore-scripts`. Build both
base paths, install the pinned browser and run `npm run test:versions` from
`website/`. This checks the actual released/development switch, then creates an
isolated local Git checkout containing two synthetic snapshots with different
Rust snippets and SVGs. It runs the production build and actual version menu
for both base paths, including the unavailable Go preference and direct reload.
The checkout never replaces the publication build. Only compact receipts under
`website/.generated/version-review/` survive; synthetic artifacts are not
publishable. The ordinary source-backed examples/browser suite remains required.

Each new historical SVG also needs an explicit immutable snapshot entry in
`docs/assets/illustrations.json`; snapshot ownership does not exempt it from the
repository-wide illustration inventory.

Rollback uses the complete previously tested site artifact and its source/run/
attempt manifest through the protected publisher. Do not roll back individual
HTML pages, snippets or assets: their identities must move together. A local
snapshot or successful build alone is not a deployment receipt. The protected
publisher and live rollback qualification are owned by the
[website CI work](ci-profiles.md) and remain separate acceptance checks.
