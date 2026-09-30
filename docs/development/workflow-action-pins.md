# GitHub Actions pin review

Executable workflows under `.github/workflows/` use immutable external action identities. A readable version comment remains next to each reviewed commit so maintainers can see the intended upstream release or moving-major line without making the workflow depend on that mutable ref.

`python3 tools/validate_workflow_actions.py` enforces the repository policy. Local actions under `./` are permitted. Repository actions and reusable workflows must use a full 40-character commit SHA and a readable version comment. Docker actions, if introduced, must use an exact `sha256` image digest and a readable version comment. Dynamic, tag, branch, short-SHA, malformed, oversized, and symlinked workflow references fail closed.

The checker parses YAML executable job/step fields, including quoted keys, flow mappings and aliases. It does not interpret `run:` script examples as actions. Local reusable workflows and composite actions are followed inside the repository; missing actions and symlinked or escaping paths are rejected. Duplicate/merge mapping keys are rejected rather than depending on ambiguous YAML interpretation. Inspection is capped at 256 executable files, 128 KiB per file, 16,384 YAML events per file and 64 nesting levels. Install the exact validator dependencies from `tools/requirements.lock` before running it.

The [ownership-local CI contracts](../testing/ci-command-contracts.md) compare all
workflow execution/security fields but do not duplicate immutable action
revisions. A same-action pin/comment-only change requires no command-contract
refresh. Action repository/path, inputs, permissions and execution position stay
reviewed. A new immutable revision is new executable code: structural equality
is not an assertion of equivalent upstream behavior. Workflow changes still
select full CI, and this pin validator still runs independently.

The action-reference parser can inspect aliases; the comprehensive workflow
contract parser deliberately rejects aliases and explicit YAML tags rather than
permit ambiguous structural comparison. The historical hash-refresh notes below
refer to the archived pre-sharding snapshot, not to an active update procedure.

## Reviewed identities

The pins introduced for Phase 3 issue #281 were resolved against the named upstream repositories on **2026-09-13**. The action version is intentionally separate from tool versions supplied through `with:`.

| Action | Reviewed upstream ref | Commit |
| --- | --- | --- |
| `actions/checkout` | `v7.0.1` | `3d3c42e5aac5ba805825da76410c181273ba90b1` |
| `actions/setup-python` | `v7.0.0` | `5fda3b95a4ea91299a34e894583c3862153e4b97` |
| `actions/setup-go` | `v5` | `40f1582b2485089dde7abd97c1529aa768e1baff` |
| `actions/setup-node` | `v7.0.0` | `820762786026740c76f36085b0efc47a31fe5020` |
| `actions/setup-java` | `v6.0.1` | `de7274f081f381c8f8158605e0321c36c376e2e6` |
| `actions/setup-dotnet` | `v6.0.0` | `a98b56852c35b8e3190ac28c8c2271da59106c68` |
| `actions/upload-artifact` | `v7.0.1` | `043fb46d1a93c77aae656e7c1c64a875d1fc6a0a` |
| `actions/download-artifact` | `v4` | `d3f86a106a0bac45b974a628896c90dbdf5c8093` |
| `actions/attest-build-provenance` | `v4.2.2` | `4d101475d8b20a2381f78447822ac1eab6504dd8` |
| `actions/upload-pages-artifact` | `v5.0.0` | `fc324d3547104276b827a68afc52ff2a11cc49c9` |
| `dtolnay/rust-toolchain` | `1.97.1` | `4716b85f2fac3e324e64fa2810f6b5c3905760a5` |
| `Swatinem/rust-cache` | `v2.9.2` | `6323deb102c322ba6fcbdcafc7e3dddab59af2b6` |
| `bytecodealliance/actions` | `v1` | `9152e710e9f7182e4c29ad218e4f335a7b203613` |
| `bufbuild/buf-setup-action` | `v1` | `a47c93e0b1648d5651a065437926377d060baa99` |
| `mlugg/setup-zig` | `v2` | `d1434d08867e3ee9daa34448df10607b98908d29` |

The `actions/setup-java` v6.0.1 identity was resolved and its action definition
reviewed on **2026-09-27**. The action uses Node 24 on the hosted runners and
retains the `distribution: temurin` and exact `java-version: '25.0.4+101.0.LTS'`
inputs selected by LSF. The JDK baseline remains Temurin 25.0.4.1+1. The workflow
hashes in `tools/ci/history/commands-v1.json` reflect the new action pin; required commands
and job conditions are unchanged.

The `actions/attest-build-provenance` v4.2.2 identity was resolved and its action
definition reviewed on **2026-09-27**. It delegates to the pinned `actions/attest`
v4.2.1 action and preserves the `subject-path` input and `bundle-path` output used
by the developer and native runtime workflows. Registry publication remains
disabled by default. The workflow hashes in `tools/ci/history/commands-v1.json` reflect the
new action pin; required commands and job conditions are unchanged.

The `actions/upload-pages-artifact` v5.0.0 identity was resolved and its action
definition reviewed on **2026-09-27**. It delegates artifact upload to the pinned
`actions/upload-artifact` v7.0.0 action and preserves the existing Pages archive,
`name`, `path` and retention inputs. Its new `include-hidden-files` input defaults
to false, preserving the site's current file selection. The Pages workflow hash
in `tools/ci/history/commands-v1.json` reflects the new pin; publication guards and required
commands are unchanged.

The `actions/checkout` v7.0.1 identity, release notes and action-definition diff
were reviewed on **2026-09-27**. It uses Node 24. All repository checkouts retain
`persist-credentials: false` and their existing refs. The new fork-PR checkout
guard remains enabled; these workflows do not use `pull_request_target` or
`workflow_run`. The reviewed workflow hashes reflect the new pin without
changing required commands or publication conditions.

The `actions/setup-python` v7.0.0 identity, release notes and action-definition
diff were reviewed on **2026-09-27**. It uses Node 24 and retains the explicitly
selected Python versions and cache inputs. These workflows do not use the
removed `pip-install` input; dependency installation still uses the existing
locked commands. The workflow hashes in `tools/ci/history/commands-v1.json` reflect the new
pin; required commands and job conditions are unchanged.

The `actions/setup-dotnet` v6.0.0 identity, release notes and action-definition
diff were reviewed on **2026-09-27**. It uses Node 24 and keeps the explicit
.NET SDK and cache inputs selected by the workflows. No new installer options
or package sources are enabled. The workflow hashes in `tools/ci/history/commands-v1.json`
reflect the new pin; required commands and job conditions are unchanged.

The `actions/upload-artifact` v7.0.1 identity, release notes and action-definition
diff were reviewed on **2026-09-28**. It uses Node 24 and retains the existing
artifact names, paths, retention, compression and hidden-file inputs. The new
`archive` input defaults to true, preserving zipped artifacts for the existing
download steps; these workflows do not enable direct single-file uploads.
The workflow identities in `tools/ci/history/commands-v1.json` reflect all updated pins.

The `actions/setup-node` v7.0.0 identity, release notes and action definition
were reviewed on **2026-09-28**. The action runs on Node 24 and retains the
workflows' explicit Node 24.19.0 version, npm cache inputs and dependency paths.
Registry authentication inputs and required install/build commands are unchanged.
Reconciled with the ownership-local CI contracts on **2026-09-29**: this is an
action pin/comment-only workflow update, so neither the active command contracts
nor the archived pre-sharding snapshot requires a hash refresh.

The shared `dtolnay/rust-toolchain` 1.97.1 identity and upstream action-definition
diff were reviewed on **2026-09-28**. That revision hardcodes Rust 1.97.1 and has
no `toolchain` input. The MSRV job therefore installs Rust 1.94.1 explicitly with
`rustup toolchain install 1.94.1 --profile minimal --no-self-update` after the
action runs. Its full and selected-package checks continue to invoke
`cargo +1.94.1`; the declared MSRV remains 1.94.1.
Reconciled with the ownership-local CI contracts on **2026-09-30**: the explicit
installation is retained in `tools/ci/contracts/workflows/ci.yml/jobs/msrv.json`,
with all existing steps and historical coverage obligations unchanged. The
archived pre-sharding snapshot is not regenerated, and the retired active
`tools/ci/commands.json` is not restored.

## Updating a pin

Action-pin updates are supply-chain changes owned by repository maintainers and must remain reviewable. Do not auto-approve or auto-merge a proposed action update.

1. Identify the intended upstream release/tag in the action's official repository. Resolve that ref to its full commit identity using GitHub's repository data, and confirm the commit belongs to the intended upstream repository. A 40-character string alone is not provenance evidence.
2. Review the upstream release notes and the diff from the currently pinned commit. For toolchain actions, keep LSF's explicit tool version inputs unchanged unless the same change intentionally updates and validates those tools.
3. Replace every affected `uses:` reference with the reviewed commit and update the adjacent readable version comment. Update the reviewed-identity table when the repository's chosen identity changes.
4. Run `python3 -m unittest tools.tests.test_validate_workflow_actions tools.tests.test_ci_contracts`, `python3 tools/validate_workflow_actions.py`, and `python3 tools/ci_coverage.py`, then run the repository validation selected for the workflow change. Do not edit command contracts for a pin/comment-only change. Workflow edits remain full-CI changes; historical 100k or measurement campaigns are not required merely to change an immutable action identity.
5. If the update regresses validation, roll back to the previously reviewed commit SHA rather than changing the version comment or policy check to hide the failure.

The workflow policy is also called from `tools/validate_contracts.sh`, so executable workflow changes cannot pass the normal full repository-contract gate with a mutable external action ref.

## Residual trust boundary

Pinning an entry action prevents a mutable Git ref from silently selecting different action source. It does **not** authenticate every executable or dependency that the action downloads at runtime. LSF therefore keeps explicit versions for Rust, Python, Go, Node.js, Java, .NET, Zig, `wasm-tools`, and Buf where the existing setup actions support them, and reviews changes to those versions separately. Transitive JavaScript dependencies embedded in an action are fixed by the selected action commit, but network-fetched tool distributions and their upstream delivery mechanisms remain part of the CI trust boundary.

The separate `docs/wiki` source branch has two executable workflows: source validation and Wiki publication. Both use checkout and Python setup and require the same reviewed pins. Its dedicated Wiki change carries this checker and its locked parser dependency; Wiki content stays on that branch. The complete pin policy will also run in the scoped/periodic security checks in #282 and the Phase 3 completion gate #240.
