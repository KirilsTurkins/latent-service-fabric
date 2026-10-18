# Release npm security backport

The [machine-readable review](release-npm-security-2026-10-18.json) records all
20 advisory identities, exact before/after lock hashes and dependency paths,
and independently reconstructed source-repair identities.

This review covers the 20 open Dependabot alerts observed on 18 October 2026. The repository default branch is `release`, at `0ad80497604b2815487e4e5c870aa8fa1f1a0a61`; the same lockfiles on `development` already contain reviewed repairs at `c5992d9ce2cfb5b1d6da9141d66a3ce5384c45b9`. This backport keeps release package scripts, non-security direct dependencies and qualification gates. The seven Angular packages move together to 22.2.1 to preserve exact peer agreement.

| Alert | Package | Lockfile | Alerted version | Backport |
| --- | --- | --- | --- | --- |
| [#10](https://github.com/KirilsTurkins/latent-service-fabric/security/dependabot/10) | `@angular/router` | `examples/renderer-profile/package-lock.json` | 22.1.7 | 22.2.1 |
| [#11](https://github.com/KirilsTurkins/latent-service-fabric/security/dependabot/11) | `http-cache-semantics` | `website/toolchain/package-lock.json` | 4.2.0 | 4.3.0 + reviewed cache repair |
| [#12](https://github.com/KirilsTurkins/latent-service-fabric/security/dependabot/12) | `http-cache-semantics` | `website/package-lock.json` | 4.2.0 | 4.3.0 + reviewed cache repair |
| [#13](https://github.com/KirilsTurkins/latent-service-fabric/security/dependabot/13) | `http-cache-semantics` | `examples/framework-compatibility/package-lock.json` | 4.2.0 | 4.3.0 + reviewed cache repair |
| [#14](https://github.com/KirilsTurkins/latent-service-fabric/security/dependabot/14) | `braces` | `examples/framework-compatibility/package-lock.json` | 3.0.3 | 3.0.3 + reviewed depth repair |
| [#15](https://github.com/KirilsTurkins/latent-service-fabric/security/dependabot/15) | `tinypool` | `examples/framework-compatibility/package-lock.json` | 1.1.1 | 2.1.2 |
| [#16](https://github.com/KirilsTurkins/latent-service-fabric/security/dependabot/16) | `tinypool` | `examples/framework-compatibility/package-lock.json` | 1.1.1 | 2.1.2 |
| [#17](https://github.com/KirilsTurkins/latent-service-fabric/security/dependabot/17) | `postcss-selector-parser` | `examples/framework-compatibility/package-lock.json` | 6.1.4 | 7.1.6 |
| [#18](https://github.com/KirilsTurkins/latent-service-fabric/security/dependabot/18) | `source-map-js` | `examples/framework-compatibility/package-lock.json` | 1.2.1 | 1.2.2 |
| [#19](https://github.com/KirilsTurkins/latent-service-fabric/security/dependabot/19) | `shell-quote` | `examples/framework-compatibility/package-lock.json` | 1.10.0 | 1.12.0 |
| [#20](https://github.com/KirilsTurkins/latent-service-fabric/security/dependabot/20) | `dompurify` | `website/package-lock.json` | 3.4.15 | 3.4.17 |
| [#21](https://github.com/KirilsTurkins/latent-service-fabric/security/dependabot/21) | `braces` | `website/package-lock.json` | 3.0.3 | 3.0.3 + reviewed depth repair |
| [#22](https://github.com/KirilsTurkins/latent-service-fabric/security/dependabot/22) | `tinypool` | `website/package-lock.json` | 1.1.1 | 2.1.2 |
| [#23](https://github.com/KirilsTurkins/latent-service-fabric/security/dependabot/23) | `tinypool` | `website/package-lock.json` | 1.1.1 | 2.1.2 |
| [#24](https://github.com/KirilsTurkins/latent-service-fabric/security/dependabot/24) | `postcss-selector-parser` | `website/package-lock.json` | 6.1.4 | 7.1.6 |
| [#25](https://github.com/KirilsTurkins/latent-service-fabric/security/dependabot/25) | `source-map-js` | `website/package-lock.json` | 1.2.1 | 1.2.2 |
| [#26](https://github.com/KirilsTurkins/latent-service-fabric/security/dependabot/26) | `katex` | `website/package-lock.json` | 0.16.47 | 0.18.2 |
| [#27](https://github.com/KirilsTurkins/latent-service-fabric/security/dependabot/27) | `dompurify` | `website/package-lock.json` | 3.4.15 | 3.4.17 |
| [#28](https://github.com/KirilsTurkins/latent-service-fabric/security/dependabot/28) | `shell-quote` | `website/package-lock.json` | 1.10.0 | 1.12.0 |
| [#29](https://github.com/KirilsTurkins/latent-service-fabric/security/dependabot/29) | `postcss-selector-parser` | `website/toolchain/package-lock.json` | 7.1.4 | 7.1.6 |

The alert API supplies no first patched version for [braces](https://github.com/advisories/GHSA-vfj7-8cjw-p6xm) or [http-cache-semantics](https://github.com/advisories/GHSA-ch52-4w7c-c8xp). The maintained braces derivative retains its upstream 3.0.3 identity and bounds the parser and all recursive AST walkers. The HTTP cache derivative retains upstream 4.3.0 and refuses reuse of security-zeroed, private, no-cache or proxy-revalidated entries through max-stale; ordinary public cache behavior remains covered. A version-only scanner may still report braces. No alert is dismissed by this change.

The archive preparer verifies complete upstream integrity and exact source preimages/postimages. The independent security verifier reconstructs both library archives and the npm bundle, checks the complete selected locks, and continues to inventory upstream package names and versions. Only the exact reviewed braces advisory revision can be classified as source-remediated. Unknown advisories, changed revisions, altered sources, aliases and lock omissions remain failures.

Before installation, run `python website/toolchain/prepare.py`; then install `website/toolchain` with `--ignore-scripts` and use its pinned npm 11.19.1 for website/framework installs. The release workflows retain every original command, timeout, gate and artifact; they add source preparation before the affected installs. The old patch-package-manager command now verifies the installed immutable bundle rather than modifying installed code.

The release security baseline separately contains 17 exceptions that expired on 3 October 2026. This backport does not renew them or relax the strict exception loader. Consequently a full Security run can remain blocked before dependency scanning; renewal needs a separate content-bound review. Dependency remediation is not a claim that the complete release security baseline is green.
