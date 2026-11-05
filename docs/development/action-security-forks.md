# Action security forks

The original fork set was rebuilt and qualified on Linux with Node 24.19.0. The
2026-10-30 source-repair revisions for setup-java, setup-node, setup-python and
upload-artifact passed locked installation, the installed-source verifier and an
unchanged distribution rebuild locally with Node 24.19.0; GitHub did not register
hosted workflows on those forks. The later cache repair passed its [focused Linux
owner](https://github.com/KirilsTurkins/lsf-cache/actions/runs/42013015089) on the
same source tree with one diagnostic workflow added. The owner did not exercise
cache save/restore integration or macOS. LSF independently reconstructs the exact
repaired deepmerge archive before crediting GHSA-gcqx-w48m-w2h4 on only the five
bound additional-action locks.
Upstream licenses and history are retained. Tool-version inputs, workflow
permissions and committed runtime distributions are preserved.

The setup-python build-graph update replaces affected build-only glob 10 with
14.0.2. Its runtime matcher retains the minimatch 10.2.5 API with an explicit
source backport for bounded pattern expansion. The security scanner verifies the
original source, exact repair, installed-source verifier, all matching lock entries
and both action bundles before crediting the reviewed advisory revision. Upstream
minimatch 10.2.5 remains an affected release. The [focused Linux owner](https://github.com/KirilsTurkins/lsf-setup-python/actions/runs/42010605694)
checked the exact published source tree with only its diagnostic workflow added;
the retained artifact includes both rebuilt bundles and the source inputs.

The Rust-cache fork retains deepmerge 4.3.1 and minimatch 10.2.6 with bounded
source repairs. Its [focused Linux owner](https://github.com/KirilsTurkins/lsf-rust-cache/actions/runs/42111587240)
reconstructed the committed distribution and completed a cache miss, save and
restore with a Rust build marker and artifact. This covers the tested Linux
cache provider and does not qualify other operating systems or cache providers.

| Upstream | Fork commit | Contribution |
| --- | --- | --- |
| `actions/setup-java` | [63c7977881fc](https://github.com/KirilsTurkins/lsf-setup-java/commit/63c7977881fc344a6ed464f7ed5e242aedc8d56c) | [PR](https://github.com/actions/setup-java/pull/1296) |
| `Swatinem/rust-cache` | [38534d49940b](https://github.com/KirilsTurkins/lsf-rust-cache/commit/38534d49940bc6c6aef1e8dfd45349a99d37f14e) | [PR](https://github.com/Swatinem/rust-cache/pull/396); [fork repair](https://github.com/KirilsTurkins/lsf-rust-cache/pull/1) |
| `actions/attest-build-provenance` | [16b356100dfe](https://github.com/KirilsTurkins/lsf-attest-build-provenance/commit/16b356100dfe77222eebe783b5e26a565b76055a) | [PR](https://github.com/KirilsTurkins/lsf-attest-build-provenance/pull/1); upstream creation blocked: pull request create failed: GraphQL: KirilsTurkins does not have the correct permissions to execute `CreatePullRequest` (createPullRequest) |
| `actions/cache` | [ec176dce9471](https://github.com/KirilsTurkins/lsf-cache/commit/ec176dce9471270c8a9be1289040c0a8fd6aa708) | [PR](https://github.com/actions/cache/pull/1804); [fork repair](https://github.com/KirilsTurkins/lsf-cache/pull/1) |
| `actions/checkout` | [4d310727149d](https://github.com/KirilsTurkins/lsf-checkout/commit/4d310727149d3abacc52b5dcb0a1c4d18b345d13) | [PR](https://github.com/actions/checkout/pull/2607) |
| `actions/deploy-pages` | [e249fe4e7520](https://github.com/KirilsTurkins/lsf-deploy-pages/commit/e249fe4e7520b3d7aa16ef72f45eeb05de6cf4f6) | [PR](https://github.com/actions/deploy-pages/pull/453); [fork repair](https://github.com/KirilsTurkins/lsf-deploy-pages/pull/1) |
| `actions/download-artifact` | [dd4ebbadbf12](https://github.com/KirilsTurkins/lsf-download-artifact/commit/dd4ebbadbf12ed34441db2712be7a193490b7fc5) | [PR](https://github.com/actions/download-artifact/pull/496); [fork repair](https://github.com/KirilsTurkins/lsf-download-artifact/pull/1) |
| `actions/setup-dotnet` | [258c92792421](https://github.com/KirilsTurkins/lsf-setup-dotnet/commit/258c927924210be905f8908a4be714e5d0daffa8) | [PR](https://github.com/actions/setup-dotnet/pull/795); [fork repair](https://github.com/KirilsTurkins/lsf-setup-dotnet/pull/1) |
| `actions/setup-go` | [1020042799f7](https://github.com/KirilsTurkins/lsf-setup-go/commit/1020042799f722e9ef016bf63106367879587a49) | [PR](https://github.com/actions/setup-go/pull/805); [fork repair](https://github.com/KirilsTurkins/lsf-setup-go/pull/1) |
| `actions/setup-node` | [34275fdec80b](https://github.com/KirilsTurkins/lsf-setup-node/commit/34275fdec80b5be172c3327cadef76aa2f3b31c6) | [PR](https://github.com/actions/setup-node/pull/1653) |
| `actions/setup-python` | [164c4cbba5d1](https://github.com/KirilsTurkins/lsf-setup-python/commit/164c4cbba5d1b03a046ac8bc25ae695bee0667a8) | [PR](https://github.com/actions/setup-python/pull/1381) |
| `actions/upload-artifact` | [d74a697ce553](https://github.com/KirilsTurkins/lsf-upload-artifact/commit/d74a697ce553b389f4219545e07c97fb8542c64f) | [PR](https://github.com/actions/upload-artifact/pull/825); [fork repair](https://github.com/KirilsTurkins/lsf-upload-artifact/pull/1) |
| `actions/upload-pages-artifact` | [28d7597d6f64](https://github.com/KirilsTurkins/lsf-upload-pages-artifact/commit/28d7597d6f6497a5d34e5ecaa1d97c510ce3556b) | [PR](https://github.com/actions/upload-pages-artifact/pull/166); [fork repair](https://github.com/KirilsTurkins/lsf-upload-pages-artifact/pull/1) |
| `bufbuild/buf-setup-action` | [483cc1af1999](https://github.com/KirilsTurkins/lsf-buf-setup-action/commit/483cc1af1999992e503ff1da69b431f7b9f3bae9) | [PR](https://github.com/KirilsTurkins/lsf-buf-setup-action/pull/1); [fork repair](https://github.com/KirilsTurkins/lsf-buf-setup-action/pull/2); upstream creation blocked: Upstream repository is archived and read-only. |
| `bytecodealliance/actions` | [1ce6e3461b7d](https://github.com/KirilsTurkins/lsf-bytecodealliance-actions/commit/1ce6e3461b7d83b4b5a5a6557870b4fdfd4386ce) | [PR](https://github.com/bytecodealliance/actions/pull/24); [fork repair](https://github.com/KirilsTurkins/lsf-bytecodealliance-actions/pull/1) |
| `mlugg/setup-zig` | [e064b42fa88a](https://github.com/KirilsTurkins/lsf-setup-zig/commit/e064b42fa88ad0859d8b54838b44f672ffd5ea7a) | [PR](https://github.com/KirilsTurkins/lsf-setup-zig/pull/1); upstream creation blocked: Upstream has disabled pull requests. |
| `actions/attest` | [5c5af1d743b6](https://github.com/KirilsTurkins/lsf-attest/commit/5c5af1d743b681abf5f53d906d2bcbbcb6da5ba2) | [PR](https://github.com/KirilsTurkins/lsf-attest/pull/1); upstream creation blocked: Upstream rejected PR creation through GraphQL and REST. |

The composite wrapper proposals are drafts until an official patched child action can replace their temporary fork reference. Rebuilt child forks remain pinned in LSF.

Snapshots come from the exact fork Git objects. Their hashes use LF line endings;
`source_sha256` retains the original byte identity. The .NET fork preserves the
official PowerShell installer's Microsoft Authenticode signature without Git
newline conversion.

Action definitions are stored with a `.snapshot` suffix as inventory data. The
graph verifier parses them explicitly, while static workflow checks continue to
scan executable workflows and local action definitions.

The repository security scan covers these exact action graphs in addition to LSF package locks. GitHub alerts on the default `release` branch remain a separate branch state; this maintenance targets `development`.
