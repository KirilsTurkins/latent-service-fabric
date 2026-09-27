# Selected developer toolkit qualification

The selected toolkit at source
`cb00bf43e3f598e0f9d4bcaea2a4853d17dea8f4` passed the complete five-entry packaged
qualification in [run 36262353069](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/36262353069).
The [aggregate report](report.json) records the actual supported platforms and
scenarios. The [independent review index](review.json) binds the original raw
observations, artifact IDs and hashes. It retains the earlier failed attempts;
none is relabelled as a pass.

The [release selection](../../../packaging/dev/release-selection.json) identifies
all ten authenticated bundles and their original publisher policies. Developer
packages came from [run 36259950144](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/36259950144);
the disposable development runtime came from
[run 36259952635](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/36259952635).
Its VM steps were intentionally skipped because it is a development fixture.
It is not the separately qualified native server release.

## Executed platform matrix

| Entry | Observed execution |
| --- | --- |
| Windows x86-64 with WSL2 | All six guest languages build and execute on the owned Linux node; isolated homes and credentials, focused tests, denied capabilities, retained restart and cleanup are checked. |
| Native Windows x86-64 | The same six-language greeting components execute in the controlled portable subset after the owned WSL distribution is removed. Cancellation here is before start. |
| Direct Linux x86-64 | The packaged Rust application runs on an isolated Ubuntu host with application networking disconnected and host compilers absent. |
| Explicit SSH to Linux x86-64 | The packaged Rust workflow uses the selected helper, strict host identity and separate unprivileged ownership. Concurrent workspaces remain isolated and callable. |
| Optional devcontainer | The generated unprivileged terminal client uses its selected Linux SSH peer, without a host Docker socket or privileged container. |

The node workflows exercise build, test, invocation, running cancellation,
compile failure with the last good revision retained, edit/watch replacement,
down, restart and owned purge. Windows/WSL also exercises genuine receipt expiry:
the original outcome becomes unknown without editing the receipt store or
changing the clock, and the controller blocks replay and conflicting mutations.
Another workspace stays callable. Cleanup preserves authored sources.

The host lifecycle observation is owned WSL termination and resume. It does not
claim physical Windows suspension. Python drives the separate test conductor;
it is absent from the packaged application's PATH. Linux prerequisites were
provisioned before disconnected execution.

## Tutorial applications and guide review

The [tutorial comparison](tutorial-review.json) records greeting, word-count and
shipping applications in Rust, C, TypeScript, Go, Java and C#: 18 applications
and 72 required cases per native platform. These native comparisons do not
establish clean-host installation, node admission or provider-clock equivalence.
The packaged matrix above provides its own installation and node observations.

The automated newcomer walkthrough uses its recorded guide source, including
the source edit, watch replacement, intentional compiler failure, diagnostics,
recovery and cleanup. Subsequent consolidated guides and downloadable setup
scripts have separate website and command checks. This report does not claim
that a human used an editor on a hosted runner or reviewed a later source.
The maintainer's accepted review and delegated guide corrections are recorded in
the [27-outcome review](../../development/phase3-guide-review.md).

## Scope and retained identities

This qualifies the controlled developer toolkit and `local-experimental-v1`
application workflow. It excludes macOS, ARM64, production Windows nodes,
hostile multitenancy and production-performance claims. The report's existing
schema uses the name `windows-only` for this five-entry support matrix; the
actual entries and language coverage above define the scope.

The original report and tutorial-review bytes are retained without Git newline
conversion. The review also records both the original CRLF selection-file hash
and the committed LF hash; only line endings differ. Bundle files, signatures,
source commits and executed outcomes are unchanged.

The [earlier qualification](../../development/windows-qualification-handoff.md)
remains evidence for its earlier package source. Neither report substitutes for
the final native server's exact-source CI, installed-VM acceptance or public
asset verification.
