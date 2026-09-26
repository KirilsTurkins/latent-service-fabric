# Review the Phase 3 learning paths

This checklist gathers the 27 required outcomes from the
[coverage inventory](../../website/content/coverage.json) for the maintainer's
newcomer review. The execution receipts are already linked from that inventory;
the maintainer confirmed completion on September 26, 2026. The accepted maintenance baseline is development `9b97ac8a13a3d83c228f4e5bee43e54d37da2bdf`. The maintainer explicitly delegated the newer developer-workflow additions and their validation without another approval. This records acceptance of the guides, not a claim that the maintainer executed every command at that exact commit.

For future reviews, review the rendered development guides at one
identified source commit, then report the row IDs that pass and any corrections.
The review can be completed in batches using the same source identity.

The maintainer, KirilsTurkins, is the sole human guide reviewer. The attempted
agent review could not access the site and supplies no review result. Keep each
row pending until the maintainer explicitly reports its outcome; automated
checks and assistant edits do not stand in for that review. The September 26
confirmation applies to all 27 rows. Subsequent setup and development-guide
corrections are covered by the maintainer's explicit delegation and retain
their own source, command and rendered-site validation.

## Record the version you reviewed

### September 26 maintainer decision

The maintainer reported: “Reviewed, though after recent changes, some additions
might be required to introduce the easier dev workflow for the guides and setup.
Dont need further approvement of me after your changes”. This accepts the
27-topic review and delegates the additional setup/workflow corrections and
their validation. The coverage inventory binds that maintenance decision to
the then-current development head. It does not invent a per-command execution
log or claim the maintainer viewed every recent commit in a browser. The
existing exact-source walkthrough receipts and the new checks retain that role.

For the public site, record the `revision` from its
[site manifest](https://kirilsturkins.github.io/latent-service-fabric/site-manifest.json),
the page URL and the development version. A local built-site review should
record the checkout commit and build result instead. If the public site still
shows an older source, it cannot establish review of newly merged guides.
Use the [website build instructions](website.md) for an exact local preview.

The required [authoring criteria](../../website/content/coverage-contract.json)
are: outcome, version/profile, prerequisites, full source, commands, expected
observations, failure cases, cleanup, deeper reference and validation level.
For each row, check that a newcomer can identify the intended result, follow
the supported setup, find complete source, understand success and failure,
and clean up. Confirm that the guide labels the scope of its actual execution
evidence and any unsupported behavior.

For the six-client rows, select each language in the rendered example controls
and inspect its specific build, ownership, cancellation and shutdown guidance.
For provider and Angular rows, follow the representative documented workflow
and compare its observable outcomes with the linked receipt. Include both the
SSR/hydration path and the [Angular CSR/static-generator walkthrough](../component-development/static-sites.md)
for the three Angular/browser rows: public-file selection, signed routing,
cutover, rollback, revocation and zero execution ownership. Record commands
you actually ran separately from receipts you only inspected. Report broken
links, inaccessible controls or unexplained output alongside content issues.

## Outcome checklist

The table below is a review aid for the existing finite contract. The linked
coverage inventory remains authoritative for prerequisites, all evidence and
review metadata. An unchecked box means no review result has been recorded.

| Reviewed | Outcome ID | Guide issue | Rendered learning paths |
| --- | --- | --- | --- |
| [x] | `evaluate-boundary` | #357 | [Start with LSF](../start/index.md) |
| [x] | `install-auth-readiness` | #357 | [Run your first node](../start/first-node.md), [Native standalone installation](../installation.md) |
| [x] | `contributor-checks` | #357 | [Operate a local node and choose a contribution](../how-to/operate-and-contribute.md) |
| [x] | `author-capsule` | #357 | [Author your first capsule](../learn/author-your-first-capsule.md) |
| [x] | `package-sign-publish` | #357 | [Author your first capsule](../learn/author-your-first-capsule.md), [Deliver, invoke and recover a capsule](../learn/deliver-and-recover-a-capsule.md) |
| [x] | `rollout-uncertain-recovery` | #357 | [Deliver, invoke and recover a capsule](../learn/deliver-and-recover-a-capsule.md), [Operate a local node and choose a contribution](../how-to/operate-and-contribute.md) |
| [x] | `client-rust` | #358 | [Invoke, cancel and recover with a client SDK](../learn/use-a-client.mdx) |
| [x] | `client-typescript` | #358 | [Invoke, cancel and recover with a client SDK](../learn/use-a-client.mdx) |
| [x] | `client-go` | #358 | [Invoke, cancel and recover with a client SDK](../learn/use-a-client.mdx) |
| [x] | `client-c` | #358 | [Invoke, cancel and recover with a client SDK](../learn/use-a-client.mdx) |
| [x] | `client-java` | #358 | [Invoke, cancel and recover with a client SDK](../learn/use-a-client.mdx) |
| [x] | `client-dotnet` | #358 | [Invoke, cancel and recover with a client SDK](../learn/use-a-client.mdx) |
| [x] | `grants-bindings` | #359 | [Invoke capabilities and recognize denied authority](../learn/use-capabilities.md), [Diagnose provider failures and preserve recovery authority](../how-to/operate-capability-providers.md) |
| [x] | `http-streaming` | #359 | [Invoke capabilities and recognize denied authority](../learn/use-capabilities.md), [Diagnose provider failures and preserve recovery authority](../how-to/operate-capability-providers.md) |
| [x] | `local-s3-blobs` | #359 | [Invoke capabilities and recognize denied authority](../learn/use-capabilities.md), [Exercise provider denial, rotation and uncertain recovery](../how-to/exercise-provider-failure-and-recovery.md), [Diagnose provider failures and preserve recovery authority](../how-to/operate-capability-providers.md) |
| [x] | `local-vault-secrets` | #359 | [Invoke capabilities and recognize denied authority](../learn/use-capabilities.md), [Exercise provider denial, rotation and uncertain recovery](../how-to/exercise-provider-failure-and-recovery.md), [Diagnose provider failures and preserve recovery authority](../how-to/operate-capability-providers.md) |
| [x] | `nats-events-triggers` | #359 | [Invoke capabilities and recognize denied authority](../learn/use-capabilities.md), [Exercise provider denial, rotation and uncertain recovery](../how-to/exercise-provider-failure-and-recovery.md), [Diagnose provider failures and preserve recovery authority](../how-to/operate-capability-providers.md) |
| [x] | `local-calls-descendants` | #359 | [Invoke capabilities and recognize denied authority](../learn/use-capabilities.md), [Diagnose provider failures and preserve recovery authority](../how-to/operate-capability-providers.md) |
| [x] | `randomness-metrics` | #359 | [Invoke capabilities and recognize denied authority](../learn/use-capabilities.md), [Diagnose provider failures and preserve recovery authority](../how-to/operate-capability-providers.md) |
| [x] | `operator-security-recovery` | #359 | [Invoke capabilities and recognize denied authority](../learn/use-capabilities.md), [Diagnose provider failures and preserve recovery authority](../how-to/operate-capability-providers.md) |
| [x] | `angular-build-profile` | #361 | [Build an Angular application and deliver it through LSF](../learn/build-and-deliver-angular.mdx), [Diagnose Angular build, delivery and hydration failures](../how-to/diagnose-angular-delivery.md), [Package an observed static site](../component-development/static-sites.md) |
| [x] | `angular-publication-routing` | #361 | [Build an Angular application and deliver it through LSF](../learn/build-and-deliver-angular.mdx), [Diagnose Angular build, delivery and hydration failures](../how-to/diagnose-angular-delivery.md), [Package an observed static site](../component-development/static-sites.md) |
| [x] | `angular-browser-workflow` | #361 | [Build an Angular application and deliver it through LSF](../learn/build-and-deliver-angular.mdx), [Diagnose Angular build, delivery and hydration failures](../how-to/diagnose-angular-delivery.md), [Package an observed static site](../component-development/static-sites.md) |
| [x] | `reference-contracts` | #237 | [Read contracts, security limits and retained evidence](../learn/read-contracts-and-evidence.md) |
| [x] | `trust-resource-architecture` | #237 | [Read contracts, security limits and retained evidence](../learn/read-contracts-and-evidence.md) |
| [x] | `retained-performance-evidence` | #237 | [Read contracts, security limits and retained evidence](../learn/read-contracts-and-evidence.md) |
| [x] | `later-phase-boundary` | #237 | [Read contracts, security limits and retained evidence](../learn/read-contracts-and-evidence.md) |

## Return review results

A short issue comment or chat response is sufficient. For example:

```text
Reviewed source: <full commit from the site manifest or local checkout>
Rendered version and URL: <development page or local build>
Rows passed: <row IDs>
Rows needing changes: <row ID, page/step, observed problem>
Walkthroughs executed: <commands and actual observations>
Receipts inspected: <linked receipt names>
Reviewer: <name or GitHub handle>
```

The maintainer records accepted rows in `website/content/coverage.json` with
the review reference, exact commit and all ten criteria. Run `npm run check`
and `npm run coverage:acceptance` from `website/` after recording results.
The acceptance command checks all required review rows and execution evidence.
It must fail if a future change removes required review or evidence. A PR merge alone does not supply
that review.

The relevant guide issues are #357, #358, #359 and #361, consumed by #237 and
the finite migration gate #345. Native installation qualification #308,
verified Pages publication and the [Wiki removal](wiki-cutover-review.md) keep
their separate completion evidence. Remove the Wiki after Phase 3 completion and
site deployment; old Wiki links and archive notices are not required. Report limitations directly; accepting a
guide does not certify an unfinished installer or deployment.
