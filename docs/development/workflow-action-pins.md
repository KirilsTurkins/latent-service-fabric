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

The current security forks were reviewed on **2026-10-26**. They extend the pins introduced for Phase 3 issue #281. The action version is intentionally separate from tool versions supplied through `with:`.

| Action | Reviewed upstream ref | Commit |
| --- | --- | --- |
| `KirilsTurkins/lsf-setup-java` | `v6.1.0` + upstream changes and security fixes ([review](https://github.com/actions/setup-java/pull/1296)) | `f041d6677134ada73c077d0c012bd78164b251a7` |
| `KirilsTurkins/lsf-rust-cache` | `v2.9.3` + upstream changes and security fixes ([review](https://github.com/Swatinem/rust-cache/pull/396)) | `476b290465f7c84db317df6e6a6e2d3c12ea3477` |
| `KirilsTurkins/lsf-attest-build-provenance` | `v4.2.2` + upstream changes and security fixes ([review](https://github.com/KirilsTurkins/lsf-attest-build-provenance/pull/1)) | `16b356100dfe77222eebe783b5e26a565b76055a` |
| `KirilsTurkins/lsf-cache` | `v6.1.0` + upstream changes and security fixes ([review](https://github.com/actions/cache/pull/1804)) | `2ff27e45011b8bcf31ef566ae84c1c923c8aea69` |
| `KirilsTurkins/lsf-checkout` | `v7.0.1` + upstream changes and security fixes ([review](https://github.com/actions/checkout/pull/2607)) | `c3024dfac542bb46ebccc7829ddf1f95e0be8da9` |
| `KirilsTurkins/lsf-deploy-pages` | `v5.0.1` + upstream changes and security fixes ([review](https://github.com/actions/deploy-pages/pull/453)) | `9290f9265d55d382005aa5f300fc4e9d5bb65cb2` |
| `KirilsTurkins/lsf-download-artifact` | `v8.0.2` + upstream changes and security fixes ([review](https://github.com/actions/download-artifact/pull/496)) | `f073ba9e3801be93f933866d4c9a748e42157e5f` |
| `KirilsTurkins/lsf-setup-dotnet` | `v6.0.0` + upstream changes and security fixes ([review](https://github.com/actions/setup-dotnet/pull/795)) | `f5bcdac7f26977ef44527f837688dd86faf648ec` |
| `KirilsTurkins/lsf-setup-go` | `v7.0.0` + upstream changes and security fixes ([review](https://github.com/actions/setup-go/pull/805)) | `3f9b437aa6b8f8b1f8c7d851365be125c6b21d9e` |
| `KirilsTurkins/lsf-setup-node` | `v7.1.0` + upstream changes and security fixes ([review](https://github.com/actions/setup-node/pull/1653)) | `c1136b2d97fe79ef645e9508b2048a222f50a170` |
| `KirilsTurkins/lsf-setup-python` | `v7.1.0` + upstream changes and security fixes ([review](https://github.com/actions/setup-python/pull/1381)) | `50257733267ef69f611231aad6b77a62adca7140` |
| `KirilsTurkins/lsf-upload-artifact` | `v7.0.2` + upstream changes and security fixes ([review](https://github.com/actions/upload-artifact/pull/825)) | `01d82cc6ae713563e8d04f36a17af500cf82a6a9` |
| `KirilsTurkins/lsf-upload-pages-artifact` | `v5.0.0` + upstream changes and security fixes ([review](https://github.com/actions/upload-pages-artifact/pull/166)) | `f6fd45bb134f6855d391ed2198e9b3d57d305a05` |
| `KirilsTurkins/lsf-buf-setup-action` | `v1.50.0` + upstream changes and security fixes ([review](https://github.com/KirilsTurkins/lsf-buf-setup-action/pull/1)) | `7e1d5f1d4a4a7d82b1ff79968166c4f50a66ce57` |
| `KirilsTurkins/lsf-bytecodealliance-actions` | `v1.1.3` + upstream changes and security fixes ([review](https://github.com/bytecodealliance/actions/pull/24)) | `9244ec9f4725400c84054e3e6ec97514cadddf53` |
| `KirilsTurkins/lsf-setup-zig` | `v2.2.1` + upstream changes and security fixes ([review](https://github.com/KirilsTurkins/lsf-setup-zig/pull/1)) | `e064b42fa88ad0859d8b54838b44f672ffd5ea7a` |
| `KirilsTurkins/lsf-attest` | `v4.2.1` + upstream changes and security fixes ([review](https://github.com/KirilsTurkins/lsf-attest/pull/1)) | `5c5af1d743b681abf5f53d906d2bcbbcb6da5ba2` |
| `dtolnay/rust-toolchain` | `1.97.1` | `4716b85f2fac3e324e64fa2810f6b5c3905760a5` |

The Java fork includes `actions/setup-java` v6.1.0 and the current upstream
changes, with Undici 6.29.1 rebuilt into setup and cleanup. It retains Node 24,
the explicit Temurin selector, cache inputs and installation steps. Optional
Maven repository inputs remain unused. The action repository migrations were
reviewed in the ownership-local workflow contracts; exact preservation fixtures
retain their command, selector, deadline and token-scope assertions.

The provenance wrapper includes `actions/attest-build-provenance` v4.2.2 and
current upstream changes. It delegates to the patched LSF `attest` fork recorded
above and preserves the `subject-path` input and `bundle-path` output. Registry
publication remains disabled by default. The child graph is scanned recursively.

The Pages wrapper includes `actions/upload-pages-artifact` v5.0.0 and current
upstream changes. It delegates upload to the patched LSF `upload-artifact`
v7.0.2 fork and preserves the existing Pages archive,
`name`, `path` and retention inputs. Its new `include-hidden-files` input defaults
to false, preserving the site's current file selection. Publication guards and
required commands remain covered by the ownership-local contracts.

The initial `actions/checkout` v7.0.1 identity, release notes and action-definition diff
were reviewed on **2026-09-27**. It uses Node 24. All repository checkouts retain
`persist-credentials: false` and their existing refs. The new fork-PR checkout
guard remains enabled; these workflows do not use `pull_request_target` or
`workflow_run`. The reviewed workflow hashes reflect the new pin without
changing required commands or publication conditions.

The initial `actions/setup-python` v7.0.0 identity, release notes and action-definition
diff were reviewed on **2026-09-27**. It uses Node 24 and retains the explicitly
selected Python versions and cache inputs. These workflows do not use the
removed `pip-install` input; dependency installation still uses the existing
locked commands. The workflow hashes in `tools/ci/history/commands-v1.json` reflect the new
pin; required commands and job conditions are unchanged. The current security
fork includes v7.1.0 while preserving LSF's explicit Python selector and cache inputs.

The `actions/setup-dotnet` v6.0.0 identity, release notes and action-definition
diff were reviewed on **2026-09-27**. It uses Node 24 and keeps the explicit
.NET SDK and cache inputs selected by the workflows. No new installer options
or package sources are enabled. The workflow hashes in `tools/ci/history/commands-v1.json`
reflect the new pin; required commands and job conditions are unchanged.

The `actions/upload-artifact` v7.0.2 identity, [release notes](https://github.com/actions/upload-artifact/releases/tag/v7.0.2)
and action definition were reviewed on **2026-10-26**. It uses Node 24 and
retains the existing artifact names, paths, retention, compression and hidden-file
inputs. The `archive` input still defaults to true. Its artifact dependency
updates download retry handling for rate-limited requests. This pin/comment-only
update requires no ownership-local command-contract or historical hash refresh.

The `actions/setup-node` v7.1.0 identity, [release notes](https://github.com/actions/setup-node/releases/tag/v7.1.0)
and action definition were reviewed on **2026-10-26**. The action runs on Node 24
and retains the workflows' explicit Node 24.19.0 version, npm cache inputs and
dependency paths. The release adds version-file support and manifest-fetch
retries; LSF continues to select its explicit version. Registry authentication
inputs and required install/build commands are unchanged. This is an action
pin/comment-only workflow update, so the ownership-local command contracts and
archived pre-sharding snapshot require no refresh.

The shared `dtolnay/rust-toolchain` 1.97.1 identity and upstream action-definition
diff were reviewed on **2026-09-28**. That revision hardcodes Rust 1.97.1 and has
no `toolchain` input. The MSRV job therefore installs Rust 1.95.0 explicitly with
`rustup toolchain install 1.95.0 --profile minimal --no-self-update` after the
action runs. Its full and selected-package checks continue to invoke
`cargo +1.95.0`; the declared MSRV remains 1.95.0.
Reconciled with the ownership-local CI contracts on **2026-09-30**: the explicit
installation is retained in `tools/ci/contracts/workflows/ci.yml/jobs/msrv.json`,
with all existing steps and historical coverage obligations unchanged. The
archived pre-sharding snapshot is not regenerated, and the retired active
`tools/ci/commands.json` is not restored.

The `actions/download-artifact` v8.0.2 identity, [release notes](https://github.com/actions/download-artifact/releases/tag/v8.0.2)
and action definition were reviewed on **2026-10-26**. It uses Node 24 and
retains the existing artifact names, IDs, destinations, run IDs and explicit
cross-run token inputs. Digest mismatches still fail by default. Its artifact
dependency improves download retries on rate-limited requests. The remaining
v8.0.1 pins now match the v8.0.2 identity already used by the other workflows;
the ownership-local command contracts and historical snapshot need no refresh.

## Updating a pin

Action-pin updates are supply-chain changes owned by repository maintainers and must remain reviewable. Do not auto-approve or auto-merge a proposed action update.

1. Identify the intended upstream release/tag in the action's official repository. Resolve that ref to its full commit identity using GitHub's repository data, and confirm the commit belongs to the intended upstream repository. A 40-character string alone is not provenance evidence.
2. Review the upstream release notes and the diff from the currently pinned commit. For toolchain actions, keep LSF's explicit tool version inputs unchanged unless the same change intentionally updates and validates those tools.
3. Replace every affected `uses:` reference with the reviewed commit and update the adjacent readable version comment. Update the reviewed-identity table when the repository's chosen identity changes.
4. Run `python3 -m unittest tools.tests.test_validate_workflow_actions tools.tests.test_ci_contracts`, `python3 tools/validate_workflow_actions.py`, and `python3 tools/ci_coverage.py`, then run the repository validation selected for the workflow change. Do not edit command contracts for a pin/comment-only change. Workflow edits remain full-CI changes; historical 100k or measurement campaigns are not required merely to change an immutable action identity.
5. If the update regresses validation, roll back to the previously reviewed commit SHA rather than changing the version comment or policy check to hide the failure.

The initial `actions/cache/restore` and `actions/cache/save` v5 identities and their
Node 24 action definitions were reviewed on **2026-09-30**. The developer compiler
cache is keyed by the committed acquisition recipes and language. Restored
archives remain untrusted: the builder checks their byte ceilings and exact
committed SHA-256 before copying them into a candidate, using the same finite
deadline as a cold download. Compiler versions and archive identities do not
change. Zig uses the explicitly selected Hexops mirror from Zig's published
[automation mirror list](https://ziglang.org/download/community-mirrors/);
acquisition has no automatic retry or source fallback.

The workflow policy is also called from `tools/validate_contracts.sh`, so executable workflow changes cannot pass the normal full repository-contract gate with a mutable external action ref.

## Residual trust boundary

Pinning an entry action prevents a mutable Git ref from silently selecting different action source. It does **not** authenticate every executable or dependency that the action downloads at runtime. LSF therefore keeps explicit versions for Rust, Python, Go, Node.js, Java, .NET, Zig, `wasm-tools`, and Buf where the existing setup actions support them, and reviews changes to those versions separately. Transitive JavaScript dependencies embedded in an action are fixed by the selected action commit, but network-fetched tool distributions and their upstream delivery mechanisms remain part of the CI trust boundary.

The separate `docs/wiki` source branch has two executable workflows: source validation and Wiki publication. Both use checkout and Python setup and require the same reviewed pins. Its dedicated Wiki change carries this checker and its locked parser dependency; Wiki content stays on that branch. The complete pin policy will also run in the scoped/periodic security checks in #282 and the Phase 3 completion gate #240.


## Action dependency coverage

The maintained security forks above are pinned by commit. `.github/security/actions.json` binds each executable entry point, including cache subactions and composite children, to byte-pinned metadata and complete npm manifest/lock snapshots. The dependency baseline scans runtime and development packages; the shell-only Rust toolchain action has no npm graph. Workflow or action changes select that scan. Unknown revisions, missing children, changed snapshots, and stale records fail closed.

For an update, rebuild and test the selected fork revision, authenticate its manifest, lock, and action metadata against that exact Git commit, then update the corresponding snapshots, hashes, and workflow pins together. Run the dependency baseline and action-graph tests before merging. [The security fork ledger](action-security-forks.md) records upstream contributions and delivery restrictions.
