# Review and promote a native runtime release

This maintainer runbook connects reviewed development source to authenticated
developer bundles, a native runtime release and versioned documentation. The
September 28, 2026 maintainer instruction authorizes `0.1.0-alpha.5` promotion,
publication and Pages deployment after the required checks. It does not waive
CI, artifact authentication, VM acceptance or configured environment reviews.

Use the [native release gate](../development/native-release-gate.md) for the
complete acceptance contract and retained alpha.4 history. That evidence keeps
its original source and archive identities; a new version requires fresh runs.
No Azure resources or simulated cloud qualification are part of this release.

## 1. Prepare and review development

Complete release changes through dedicated PRs into `development`, with
successful CI and squash/admin merges. Synchronize workspace and SDK versions,
lockfiles, the reviewed security inventory and current setup guides. C and Go
source SDKs use the repository release tag. Preserve historical documentation
snapshots, receipts and published tags.

Build new developer tools and a disposable native test node from the same exact
versioned source using `Developer tools` and `Native runtime candidate`.
Select `development_test_node: true` for the latter. Independently select the
repository, workflow, source ref, commit, version and candidate purpose before
consuming their attestations.

Run `Packaged developer qualification` against those exact successful run IDs
and policies for Linux, Windows and WSL2. Select only the newly authenticated
artifacts in `packaging/dev/release-selection.json`, recording their real sizes
and hashes. Merge that selection through a reviewed PR. Never rename alpha.4
bundles to imply an alpha.5 build or copy their hashes into the new selection.

## 2. Authenticate the actual predecessor

Alpha.5 selects the published alpha.4 runtime as its predecessor:

| Identity | Selection |
| --- | --- |
| Version | `0.1.0-alpha.4` |
| Source | `2d6cc2eafc0a17dfe573be4252fa49835bebbbd6` |
| Release run | [36278662081](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/36278662081) |
| Archive SHA-256 | `a823a3c5b06ee81a09e39053451e768ee7b22199e37c3b524f89843db7b045b3` |

Inspect the immutable tag and completed run. Download its native artifact to a
new private directory, then follow the
[independent bootstrap verification sequence](../../packaging/linux/INSTALL.md#prerequisites-and-independent-bootstrap-trust).
Require the release workflow's tag/source/signer identities and check every
listed digest before running downloaded code. The predecessor entry in
`packaging/linux/compatibility.json` must match the authenticated manifest.

Installer/configuration formats remain 1 with no migration selected. This
declaration alone is not proof of compatibility: the final native VM campaign
must install alpha.4, preserve its state while upgrading, and reject an
unsupported downgrade. The older rc.2 pair remains historical alpha.4 evidence.

## 3. Promote the complete source

Open the development-to-release promotion PR. Confirm its final tree contains
all reviewed runtime, SDK, helper, dependency and documentation changes. After
successful CI, squash merge with `--admin`, then require successful CI at the
actual resulting release commit. A pre-merge PR commit is a different identity.

Inspect the registered native release workflow and its protected
`native-runtime-publish` environment. Create the immutable `0.1.0-alpha.5` tag
once at that exact release commit. Do not move an existing tag to a rebuild.

## 4. Qualify and publish the runtime

Dispatch `.github/workflows/native-runtime-release.yml` **at the tag**, supplying:

| Input | Value |
| --- | --- |
| `version` | `0.1.0-alpha.5` |
| `commit` | The exact tagged release commit |
| `ci_run` | Successful CI for that exact commit |
| `predecessor_run` | `36278662081` |
| `publish` | `true`, under the maintainer's publication authorization |

The workflow builds and attests the actual archive, authenticates the committed
developer selection, and boots real Ubuntu VMs for `local-experimental-v1` and
`external-capsule-v1`. Both must pass installation, retained state, reboot, the
declared upgrade and unsupported downgrade rejection. Require
`acceptanceComplete: true`, empty gaps and the exact artifact/source identities.
An ordinary candidate run or same-version reinstall cannot satisfy this gate.

Review the protected publication job only after those checks succeed. Do not
disable protection or manufacture successful receipts. If publication reports
an uncertain result, inspect the remote release and the gate's retained journal
before any retry; published assets must not be silently overwritten.

Upload the exact qualified developer assets named by the authenticated selection
and their verification material. Describe additions, installation paths, the
upgrade pair and remaining limitations in the release notes. Independently
verify public asset inventory, sizes, hashes and publisher identities.

## 5. Publish the matching website

Create a new documentation snapshot bound to the actual runtime release commit,
reviewed documentation commit and example source. Keep previous snapshots
immutable and follow [versioned documentation](../development/website-versions.md).
Merge the snapshot through `development` and require its successful push CI and
website artifact.

Use the single `.github/workflows/docs-pages.yml` publisher on `release`, with
that exact development source, CI run and attempt. Complete its configured
environment review and live browser checks. A source merge does not deploy Pages.
Verify live source identity, the alpha.5 selector, setup downloads, language tabs
and new web/container guide navigation before reporting completion.
