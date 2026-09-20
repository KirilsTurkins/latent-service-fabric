# Protected documentation publication evidence

The [documentation site](https://kirilsturkins.github.io/latent-service-fabric/) was published and then redeployed through the protected `github-pages` environment on 20 September 2026. Both runs completed deployment identity checks and real live-browser validation.

| Operation | Reviewed source and exact CI input | Successful publisher |
| --- | --- | --- |
| Initial publication | `80d7924a6e203b88c889f4b9bd3f6afb2f0fe48c`, CI `35534853488`, attempt `1` | [35536167924](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/35536167924), attempt `1` |
| Controlled redeployment via rollback mode | The same previously published complete artifact, with expected live source checked again after approval | [35537527420](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/35537527420), attempt `1` |

The recovery exercise restored the same known site artifact; it does not claim a change between two different documentation revisions. The rollback route required the successful previous publisher receipt and the exact live source, then restaged and reverified the complete site. Both deployments used trusted publisher source `af3e8680d4132bd99b3299e300af147e53b7fa80` on the default `release` branch. Pull-request content and dependency installation ran without Pages deployment credentials.

The immutable CI artifact was `10612956062`, digest `sha256:4d1f14bce0b23b32e8e86ba0ed5fb232ab3e83b305ba6d71afeae904f2e1fc75`. Both reviewed candidates contained 692 files with tree digest `sha256:8adfdfe4de767b506c8290e4ad43139629bbcde28f30dff3c8bd1eb1e1a0903e` and manifest digest `sha256:e5e98801a44ce3fd06da417ff6993b3ef6a6812ffdbf92b689dd7bf6d02f8804`. Example and released-snapshot identities remain in the raw receipts.

Live Chromium 153.0.8010.12 checks passed for home, direct nested reload, static assets, selected-version search, version switching, catalogue navigation, development source examples, actual code copy and missing-route HTTP 404. Both browser receipts report zero browser errors.

- [Initial publication receipt](../evidence/pages-2026-09-20/publication.json) and [live browser receipt](../evidence/pages-2026-09-20/publication-browser.json).
- [Controlled redeployment receipt](../evidence/pages-2026-09-20/redeployment.json) and [live browser receipt](../evidence/pages-2026-09-20/redeployment-browser.json).

The environment requires the configured repository maintainer reviewer and permits the `release` deployment branch. Candidates were reviewed against their source, run, attempt, immutable artifact and staged bytes before approval; no environment bypass was used. Pages serves static documentation. These operations neither publish a node runtime release nor certify Phase 3 or the final essential-guide review.

The [publication procedure](website-publication.md) documents refusal handling, protected recovery, artifact retention and the bounded adversarial fixtures. Final content coverage and human pedagogy review remain owned by #345 and its guide tickets.
