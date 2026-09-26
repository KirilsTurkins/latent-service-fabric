# Protected documentation publication

The approved content authority is the exact head of `development`. One complete
site contains the reviewed historical snapshots and a clearly labelled
development channel. The `release` default branch owns the trusted
[`docs-pages.yml`](../../.github/workflows/docs-pages.yml) publisher and its
[`policy`](../../tools/docs_pages_policy.py). Registering that minimal workflow
on `release` does not promote the runtime or copy the whole development branch.

The ordinary unprivileged [site workflow](../../.github/workflows/docs-site.yml)
builds, checks and uploads `docs-site-SHA-RUN-ATTEMPT`. Publication accepts only a
successful **push** CI run for the same repository and `development` commit,
with its exact successful attempt and a successful security baseline. A PR merge
artifact, fork artifact, similarly named archive or earlier failed attempt is
ineligible. Website builds, MDX, npm and browser tools never receive Pages write
or OIDC authority.

## Prepare and approve a publication

1. Merge the intended source through its reviewed PR. Wait for its development
   push CI and security baseline to finish successfully. Record the source SHA,
   CI run and attempt; confirm the site artifact contains all browser receipts.
2. Dispatch **Protected documentation publication** on `release`, with mode
   `publish` and those exact values. The bounded selector verifies GitHub origin,
   artifact digest, safe regular-file paths, complete browser receipts, clean
   source identity, project base path and absence of synthetic publications.
3. Review the staged source/run/attempt and approve the `github-pages`
   environment. Configure that environment for the `release` branch and required
   maintainer review; do not bypass the review for an initial deployment.
4. The deployment job verifies every staged byte and checks the current
   development head again after approval. If another merge advanced it, the run
   fails before publication; select the newer tested artifact in a new run.

Only the deploy job has `pages:write` and `id-token:write`. It executes trusted
publisher code from the dispatch's immutable release commit and pinned Actions,
with candidate site files treated as data. The single concurrency group does
not cancel an active deployment. Each job has a ten-minute bound. Site archives
are limited to 128 MiB compressed, 256 MiB expanded, 6000 entries and 8 MiB per
file; paths, duplicates, symlinks and special files fail closed. These limits do
not alter runtime budgets or turn website files into a package authority.

The live `publication.json` records the source, CI run/attempt, exact artifact
identity, complete site-tree digest and publisher run/attempt/source. The
publisher checks that record, direct routes and the source manifest, then an
unprivileged real browser verifies home/nested navigation, an actual image,
version switching, a source-backed Rust example, copied code, selected-version
search, catalogue filtering and a real missing-route 404. The older alpha's
missing SDK examples remain unavailable; development code is never presented as
historical alpha code.

## Restore a known complete site

Keep the previous successful publisher run plus its matching successful CI run,
attempt, source and artifact. Artifacts and compact publication/browser receipts
are retained for 14 days. Expired or deleted artifacts cannot be restored through
this workflow; rebuilding is a new reviewed publication, not the same artifact.

Dispatch mode `rollback`, supplying that previous CI source/run/attempt, the
successful `previous_publication_run`, and the exact `expected_live_source` to
replace. Selection requires the prior successful release-branch publisher's
receipt to bind the same immutable CI artifact. After environment approval, the
live source must still match the expected value. The complete old site is
restored together, including its historical documents, examples, assets and
search index. A new publication record identifies this rollback run. Partial
directory uploads and arbitrary old CI artifacts are not rollback inputs.

If deployment or live verification fails, retain the failed run and inspect the
live publication identity. A failed or interrupted run cannot become prior
successful rollback evidence. Start a new protected deployment with explicit
inputs; the publisher never automatically retries a mutation or silently
substitutes another artifact.

## Validation and completion boundary

`python3 -m unittest tools.tests.test_docs_pages` covers rejected PR/fork/wrong
workflow/branch/attempt sources, missing and substituted artifacts, path attacks,
size limits, dirty/wrong/synthetic site identities, staged-byte tampering and
stale publication/rollback guards. These synthetic cases do not publish a site.

The [20 September publication evidence](website-publication-evidence.md) records
the actual protected deployment, live browser checks and controlled redeployment
of the known complete artifact required by #355. The final guide coverage and human pedagogy review remain owned by
#345 and its content tickets. GitHub Pages serves static documentation; it does
not host an LSF runtime or management credentials.
