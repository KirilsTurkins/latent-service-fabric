# Action security forks

These forks were rebuilt and qualified on Linux with Node 24.19.0. Full npm graphs, including development tools, have zero OSV findings at the recorded revisions. Upstream licenses and history are retained. Tool-version inputs and workflow permissions are preserved.

| Upstream | Fork commit | Contribution |
| --- | --- | --- |
| `actions/setup-java` | [f041d6677134](https://github.com/KirilsTurkins/lsf-setup-java/commit/f041d6677134ada73c077d0c012bd78164b251a7) | [PR](https://github.com/actions/setup-java/pull/1296) |
| `Swatinem/rust-cache` | [476b290465f7](https://github.com/KirilsTurkins/lsf-rust-cache/commit/476b290465f7c84db317df6e6a6e2d3c12ea3477) | [PR](https://github.com/Swatinem/rust-cache/pull/396) |
| `actions/attest-build-provenance` | [16b356100dfe](https://github.com/KirilsTurkins/lsf-attest-build-provenance/commit/16b356100dfe77222eebe783b5e26a565b76055a) | [PR](https://github.com/KirilsTurkins/lsf-attest-build-provenance/pull/1); upstream creation blocked: pull request create failed: GraphQL: KirilsTurkins does not have the correct permissions to execute `CreatePullRequest` (createPullRequest) |
| `actions/cache` | [2ff27e45011b](https://github.com/KirilsTurkins/lsf-cache/commit/2ff27e45011b8bcf31ef566ae84c1c923c8aea69) | [PR](https://github.com/actions/cache/pull/1804) |
| `actions/checkout` | [c3024dfac542](https://github.com/KirilsTurkins/lsf-checkout/commit/c3024dfac542bb46ebccc7829ddf1f95e0be8da9) | [PR](https://github.com/actions/checkout/pull/2607) |
| `actions/deploy-pages` | [9290f9265d55](https://github.com/KirilsTurkins/lsf-deploy-pages/commit/9290f9265d55d382005aa5f300fc4e9d5bb65cb2) | [PR](https://github.com/actions/deploy-pages/pull/453) |
| `actions/download-artifact` | [f073ba9e3801](https://github.com/KirilsTurkins/lsf-download-artifact/commit/f073ba9e3801be93f933866d4c9a748e42157e5f) | [PR](https://github.com/actions/download-artifact/pull/496) |
| `actions/setup-dotnet` | [f5bcdac7f269](https://github.com/KirilsTurkins/lsf-setup-dotnet/commit/f5bcdac7f26977ef44527f837688dd86faf648ec) | [PR](https://github.com/actions/setup-dotnet/pull/795) |
| `actions/setup-go` | [3f9b437aa6b8](https://github.com/KirilsTurkins/lsf-setup-go/commit/3f9b437aa6b8f8b1f8c7d851365be125c6b21d9e) | [PR](https://github.com/actions/setup-go/pull/805) |
| `actions/setup-node` | [c1136b2d97fe](https://github.com/KirilsTurkins/lsf-setup-node/commit/c1136b2d97fe79ef645e9508b2048a222f50a170) | [PR](https://github.com/actions/setup-node/pull/1653) |
| `actions/setup-python` | [50257733267e](https://github.com/KirilsTurkins/lsf-setup-python/commit/50257733267ef69f611231aad6b77a62adca7140) | [PR](https://github.com/actions/setup-python/pull/1381) |
| `actions/upload-artifact` | [01d82cc6ae71](https://github.com/KirilsTurkins/lsf-upload-artifact/commit/01d82cc6ae713563e8d04f36a17af500cf82a6a9) | [PR](https://github.com/actions/upload-artifact/pull/825) |
| `actions/upload-pages-artifact` | [e54978b28134](https://github.com/KirilsTurkins/lsf-upload-pages-artifact/commit/e54978b2813471fa30a16e21358d1fc3acd9e009) | [PR](https://github.com/actions/upload-pages-artifact/pull/166) |
| `bufbuild/buf-setup-action` | [7e1d5f1d4a4a](https://github.com/KirilsTurkins/lsf-buf-setup-action/commit/7e1d5f1d4a4a7d82b1ff79968166c4f50a66ce57) | [PR](https://github.com/KirilsTurkins/lsf-buf-setup-action/pull/1); upstream creation blocked: Upstream repository is archived and read-only. |
| `bytecodealliance/actions` | [9244ec9f4725](https://github.com/KirilsTurkins/lsf-bytecodealliance-actions/commit/9244ec9f4725400c84054e3e6ec97514cadddf53) | [PR](https://github.com/bytecodealliance/actions/pull/24) |
| `mlugg/setup-zig` | [e064b42fa88a](https://github.com/KirilsTurkins/lsf-setup-zig/commit/e064b42fa88ad0859d8b54838b44f672ffd5ea7a) | [PR](https://github.com/KirilsTurkins/lsf-setup-zig/pull/1); upstream creation blocked: Upstream has disabled pull requests. |
| `actions/attest` | [5c5af1d743b6](https://github.com/KirilsTurkins/lsf-attest/commit/5c5af1d743b681abf5f53d906d2bcbbcb6da5ba2) | [PR](https://github.com/KirilsTurkins/lsf-attest/pull/1); upstream creation blocked: Upstream rejected PR creation through GraphQL and REST. |

The composite wrapper proposals are drafts until an official patched child action can replace their temporary fork reference. Rebuilt child forks remain pinned in LSF.

Snapshots come from the exact fork Git objects. Their hashes use LF line endings;
`source_sha256` retains the original byte identity. The .NET fork preserves the
official PowerShell installer's Microsoft Authenticode signature without Git
newline conversion.

The repository security scan covers these exact action graphs in addition to LSF package locks. GitHub alerts on the default `release` branch remain a separate branch state; this maintenance targets `development`.
