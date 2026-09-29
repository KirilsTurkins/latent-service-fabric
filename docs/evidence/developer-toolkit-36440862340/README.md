# Alpha.5 developer toolkit checks

The alpha.5 toolkit at source
`42e549dd86b902ce887643b3bb339bb2a9ad8f50` passed both complete packaged schedules
in [run 36440862340](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/36440862340).
The [review index](review.json) records the original observations, artifact
identities, cleanup results and authenticated selection. No raw receipt has
been rewritten to change its result or scope.

The [release selection](https://github.com/KirilsTurkins/latent-service-fabric/blob/0.1.0-alpha.5/packaging/dev/release-selection.json) contains
41 files across ten authenticated bundles. Developer packages came from
[run 36390061275](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/36390061275);
the disposable native test node came from
[run 36390058387](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/36390058387).
Their exact workflow, branch, source, version and hosted publisher identities
were verified before checking every selected checksum and archive identity.

| Platform | Observed checks |
| --- | --- |
| Windows x86-64 with WSL2 | All six languages build and execute on the owned Linux node; isolated workspaces, restart, edit/watch, cancellation and source-preserving cleanup pass. |
| Native Windows x86-64 | The same six-language components pass the supported portable cases after the owned WSL distribution is removed. |
| Direct Linux x86-64 | The installed Rust application runs without an LSF source checkout or runtime compiler; retained restart and the closed node profile pass. |
| Explicit SSH to Linux x86-64 | The Rust workflow uses a selected helper and pinned peer identity; concurrent workspaces remain isolated. |
| Optional devcontainer | The generated unprivileged client uses its selected SSH peer, without a privileged container or host Docker socket. |

The dedicated Windows recovery schedule also passed actual receipt expiry,
unknown-outcome retention and rejection of conflicting replay. It preserves the
original operation journals. The node schedules verify cancellation during
execution; native portable cancellation covers the separate before-start case.
The automated newcomer walkthrough and its guide source are recorded in the
review index. No new human editor review or physical host suspension is claimed.

The individual probes retain `qualificationComplete: false`: each is an
observation, not an independent product or publication sign-off. The complete
workflow passed, and its scope remains the controlled developer toolkit with
the documented local node profile. macOS, ARM64, production Windows nodes,
hostile multitenancy and production performance remain outside these checks.
The GitHub runner's kernel name does not qualify Azure Container Apps or storage.

The earlier failed native build is retained in the review index. Its standalone
fixture lock was repaired before the selected candidates were built. The
[alpha.4 observations](../developer-toolkit-36262353069/README.md) keep their
original identities. Server publication has its separate
[native release gate](../../development/native-release-gate.md#published-alpha5-evidence).

All 41 files were also downloaded from the public alpha.5 release and checked
against the qualified selection; all ten original publisher signatures were
authenticated again. The [public download record](public-downloads.json) keeps
their exact byte identities.

The [original qualification archive](https://github.com/KirilsTurkins/latent-service-fabric/releases/download/0.1.0-alpha.5/developer-qualification-0.1.0-alpha.5.zip)
retains all eight original observation/selection files and the review index.
It is 743,737 bytes, SHA-256
`37547dab768bf37ae4b4f10eb22a48208034e5346b620ea70dc6b620b8087540`.
