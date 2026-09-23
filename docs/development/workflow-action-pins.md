# GitHub Actions pin review

Executable workflows under `.github/workflows/` use immutable external action identities. A readable version comment remains next to each reviewed commit so maintainers can see the intended upstream release or moving-major line without making the workflow depend on that mutable ref.

`python3 tools/validate_workflow_actions.py` enforces the repository policy. Local actions under `./` are permitted. Repository actions and reusable workflows must use a full 40-character commit SHA and a readable version comment. Docker actions, if introduced, must use an exact `sha256` image digest and a readable version comment. Dynamic, tag, branch, short-SHA, malformed, oversized, and symlinked workflow references fail closed.

The checker parses YAML executable job/step fields, including quoted keys, flow mappings and aliases. It does not interpret `run:` script examples as actions. Local reusable workflows and composite actions are followed inside the repository; missing actions and symlinked or escaping paths are rejected. Duplicate/merge mapping keys are rejected rather than depending on ambiguous YAML interpretation. Inspection is capped at 256 executable files, 128 KiB per file, 16,384 YAML events per file and 64 nesting levels. Install the exact validator dependencies from `tools/requirements.lock` before running it.

## Reviewed identities

The pins introduced for Phase 3 issue #281 were resolved against the named upstream repositories on **2026-09-13**. The action version is intentionally separate from tool versions supplied through `with:`.

| Action | Reviewed upstream ref | Commit |
| --- | --- | --- |
| `actions/checkout` | `v4` | `11d5960a326750d5838078e36cf38b85af677262` |
| `actions/setup-python` | `v5` | `a26af69be951a213d495a4c3e4e4022e16d87065` |
| `actions/setup-go` | `v5` | `40f1582b2485089dde7abd97c1529aa768e1baff` |
| `actions/setup-node` | `v4` | `49933ea5288caeca8642d1e84afbd3f7d6820020` |
| `actions/setup-java` | `v4` | `cf277c60eb25467037889841efdb72551f06f6c3` |
| `actions/setup-dotnet` | `v4` | `67a3573c9a986a3f9c594539f4ab511d57bb3ce9` |
| `actions/upload-artifact` | `v4` | `ea165f8d65b6e75b540449e92b4886f43607fa02` |
| `actions/download-artifact` | `v4` | `d3f86a106a0bac45b974a628896c90dbdf5c8093` |
| `actions/download-artifact` (Pages publisher) | `v8.0.1` | `3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c` |
| `actions/deploy-pages` | `v5.0.1` | `368f82528645a54fb793d4d04e342629a3f51346` |
| `dtolnay/rust-toolchain` | `1.97.1` | `4716b85f2fac3e324e64fa2810f6b5c3905760a5` |
| `dtolnay/rust-toolchain` | `1.94.1` | `9376cdc5a5e25b16da71af47712785cf06b0d6d4` |
| `Swatinem/rust-cache` | `v2.9.2` | `6323deb102c322ba6fcbdcafc7e3dddab59af2b6` |
| `bytecodealliance/actions` | `v1` | `9152e710e9f7182e4c29ad218e4f335a7b203613` |
| `bufbuild/buf-setup-action` | `v1` | `a47c93e0b1648d5651a065437926377d060baa99` |
| `mlugg/setup-zig` | `v2` | `d1434d08867e3ee9daa34448df10607b98908d29` |

The upstream `actions/setup-java@v4` line is deprecated as of the reviewed commit. This pin records the behavior already selected by the repository; moving to another major action line is a separate dependency change that requires its own compatibility review.

The active Pages publisher uses the same two artifact-download and deployment
identities already reviewed on `development`. Their official release tags were
resolved again on September 23, 2026. This maintenance change preserves the exact
artifact/source checks, required environment review and sole publisher.

## Updating a pin

Action-pin updates are supply-chain changes owned by repository maintainers and must remain reviewable. Do not auto-approve or auto-merge a proposed action update.

1. Identify the intended upstream release/tag in the action's official repository. Resolve that ref to its full commit identity using GitHub's repository data, and confirm the commit belongs to the intended upstream repository. A 40-character string alone is not provenance evidence.
2. Review the upstream release notes and the diff from the currently pinned commit. For toolchain actions, keep LSF's explicit tool version inputs unchanged unless the same change intentionally updates and validates those tools.
3. Replace every affected `uses:` reference with the reviewed commit and update the adjacent readable version comment. Update the reviewed-identity table when the repository's chosen identity changes.
4. Run `python3 -m unittest tools.tests.test_validate_workflow_actions` and `python3 tools/validate_workflow_actions.py`, then run the repository validation selected for the workflow change. Workflow edits remain full-CI changes; historical 100k or measurement campaigns are not required merely to change an immutable action identity.
5. If the update regresses validation, roll back to the previously reviewed commit SHA rather than changing the version comment or policy check to hide the failure.

The workflow policy is also called from `tools/validate_contracts.sh`, so executable workflow changes cannot pass the normal full repository-contract gate with a mutable external action ref.

## Residual trust boundary

Pinning an entry action prevents a mutable Git ref from silently selecting different action source. It does **not** authenticate every executable or dependency that the action downloads at runtime. LSF therefore keeps explicit versions for Rust, Python, Go, Node.js, Java, .NET, Zig, `wasm-tools`, and Buf where the existing setup actions support them, and reviews changes to those versions separately. Transitive JavaScript dependencies embedded in an action are fixed by the selected action commit, but network-fetched tool distributions and their upstream delivery mechanisms remain part of the CI trust boundary.

The separate `docs/wiki` source branch has two executable workflows: source validation and Wiki publication. Both use checkout and Python setup and require the same reviewed pins. Its dedicated Wiki change carries this checker and its locked parser dependency; Wiki content stays on that branch. The complete pin policy will also run in the scoped/periodic security checks in #282 and the Phase 3 completion gate #240.
