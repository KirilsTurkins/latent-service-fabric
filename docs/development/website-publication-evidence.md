# Protected documentation publication evidence

## Complete alpha.4 site, 2026-09-27

The complete development and alpha.4 documentation is live at the
[documentation website](https://kirilsturkins.github.io/latent-service-fabric/).
The complete site was published from `69a7b30dd89b298254a16b049180bbd9082ecdec` through
[push CI 36285745230](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/36285745230), attempt 1, and
[protected publisher 36287023135](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/36287023135), attempt 1.
The immutable site artifact is `10920985707`,
digest `sha256:13cbc99efb2e26e5302209f03b76f31b47c9595e2effa70969ed158804852727`; the deployed tree digest is
`sha256:446a84536f367bb04290b4fd062e1a7201fa005a230e05edd7a837e485efb748`. The original publication, live-browser, build/theme/
example/version/discovery receipts and final Wiki observations are retained in
[documentation-validation-36287023135.zip](https://github.com/KirilsTurkins/latent-service-fabric/releases/download/0.1.0-alpha.4/documentation-validation-36287023135.zip), 13,532 bytes, SHA-256
`ecfbb7f76aec1bb41c10bade136b2f8b3445512bc29e5644a22ca1175abd1834`. Its public bytes were independently verified. This
supplemental archive is separate from the native publisher's attested assets.

The site contains 579 pages and both alpha.4 and alpha.3 snapshots.
Live Chromium checks passed home, nested reloads, assets, version switching,
six-language alpha.4 code selection/copy, current source examples, selected-version
search, catalogue navigation and missing-route HTTP 404, with zero browser errors.
The protected environment approval reviewed the independently staged exact bytes;
no environment protection was removed or bypassed.

The [final Wiki observation](wiki-cutover-review.md) verifies all 26 mapped entries
across 20 maintained destinations and confirms the disabled Wiki and
both retired writers. The maintainer's accepted guide review remains separately
recorded in the [27-outcome checklist](phase3-guide-review.md).

The controlled rollback/redeployment exercise below keeps its original identity.
It was not rerun or relabelled as this new publication. Subsequent engineering-doc
publications use the same protected complete-artifact flow and retain their own
source/CI/artifact/publisher receipts.

## Initial publication and recovery exercise, September 20

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

At publication, the environment required the configured repository maintainer reviewer and permitted the `release` deployment branch. Candidates were reviewed against their source, run, attempt, immutable artifact and staged bytes before approval; no environment bypass was used. Pages serves static documentation. These operations neither publish a node runtime release nor certify Phase 3 or the final essential-guide review.

The [publication procedure](website-publication.md) documents refusal handling, protected recovery, artifact retention and the bounded adversarial fixtures. The original operation did not complete the later content or human-review gate.
That acceptance and the complete-site publication are recorded above.
