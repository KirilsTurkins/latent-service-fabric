# Native release gate

This is the maintainer gate for [native standalone installation](../installation.md)
and [#308](https://github.com/KirilsTurkins/latent-service-fabric/issues/308), not a
claim that a binary release or its full acceptance evidence already exists.
The parent integrator chooses the final reviewed commit and new version only
after exact-head CI. Do not move the historical source-only `0.1.0-alpha.3` tag.

## Publisher identity and offline verification

The publisher is `KirilsTurkins/latent-service-fabric`, specifically
`.github/workflows/native-runtime-release.yml@refs/tags/<approved-version>`,
authenticated by GitHub's OIDC issuer `https://token.actions.githubusercontent.com`.
Both source and signer commit must equal the independently approved full commit.
Only GitHub-hosted runners are accepted. The checksum inventory authenticates the
archive, manifest and bootstrap; downloaded Python is never the first verifier.
An independently provisioned GitHub CLI 2.96.0+, Sigstore roots and exact identity
policy are prerequisites. The [operator verification commands](../../packaging/linux/INSTALL.md#prerequisites-and-independent-bootstrap-trust)
use local attestation material and roots without GitHub login or online refresh.

The dedicated candidate workflow has a **different** certificate identity:
`.github/workflows/native-runtime.yml@refs/heads/<candidate-branch>`. Its exact
source policy requires `--allow-candidate`; it cannot silently become release
authority. Neither a new project Ed25519 bootstrap key nor an artifact-supplied
root is an independent trust anchor. Capsule admission policy is separate.

## Exact source and prerequisites

The builder checks clean source before and after the build, exact commit and
workspace version, Cargo.lock, pinned Rust/wasm-tools and observed ELF identities.
It builds `latent`, `latentd`, `latent-aot-compiler`, and the maintained echo
component with its manifests and WIT inputs. The archive includes SPDX, observed
build provenance and license texts; no private test keys or expiring admission
policy are runtime assets. This is not a reproducible-build or SLSA-level claim.

Some locked upstream crates omit their monorepo root license. The reviewed
[license source inventory](../../packaging/linux/license-sources.json) maps only
those exact package versions to the upstream root license, exact VCS revision,
donor crate and license digest. The builder verifies both published crate VCS
records and locked checksums and records the donor in SPDX. It does not substitute
generic SPDX text for unknown licensing or fetch a moving upstream branch.

GitHub runner workspaces can have extended ACLs. Native jobs clone the same exact
checkout into a fresh private `/tmp/lsf-native-*/source` on the disposable host,
without hard links or changes to the original checkout, runner ACLs or installer
path policy. This is host build/test infrastructure, not a guest prerequisite.
The installer continues to reject extended ACLs and unsafe owners and ancestors.

## Real VM evidence

The [candidate workflow](../../.github/workflows/native-runtime.yml) builds and
attests real native artifacts before starting two QEMU guests. The
[release workflow](../../.github/workflows/native-runtime-release.yml) performs
the same matrix with the release certificate identity and selected predecessor.
Both use the pinned Ubuntu image in [the VM profile](../../tools/native-vm-profile.json),
two CPUs, 3 GiB RAM and a bounded disk. Host QEMU/KVM tooling is allowed; there is
no Docker/Podman/orchestrator or guest Rust/C/C++/Wasm build toolchain. The guest
installs no packages. Its independently installed `gh`, roots and test inputs are
provisioned separately from the runtime archive. SSH host keys are pinned before
boot, passwords are locked, and QEMU networking permits only the controller's
SSH connection. Verification is also run in an isolated network namespace.

`tools/run_native_vm.py` owns/reaps QEMU and bounds downloads, SSH operations,
boot waits, guest commands and output. It retains only a compact JSON receipt:
source/archive identity, publisher/root/verifier hashes, image/kernel/acceleration,
actual boot IDs, phase results and bounded redacted failure diagnostics. It never
uploads VM disks, SSH private keys, AOT keys, credentials or state backups.

The guest exercises:

- Authentication before downloaded bootstrap execution; actual offline signature
  checks reject tampering, missing attestations and incorrect source/repository.
- A non-root systemd node, authenticated activation readiness, loopback binding,
  protected paths, unsupported host/profile, and actual permission rejection.
- Ordinary local Wasmtime and enforced isolated AOT without sandbox fallback.
  The latter uses fresh synthetic test trust through the public operator API.
  A separately attested test-only helper signs the exact bundled component; keys
  stay in helper memory, never become defaults, and are not installed in the guest.
- Actual publish/deploy/invoke and a retained invocation after `systemctl reboot`
  changes the boot ID; same-version installation preserves identity and settings.
- Invocation-scoped clean shutdown, a stopped consistent private backup,
  deliberately rejected corrupt configuration and restoration of the full set.
- Removal preserving operator state, reinstall and retained invocation, distinct
  installation-ID-confirmed purge and unsafe-path rejection.
- An actual non-root foreground evaluation with no system service or `/etc`
  changes, retained invocation and live-removal exclusion.
- When a predecessor is selected, a fresh old-version installation, real managed
  publication, explicit compatible upgrade retaining it, optional explicitly
  approved compiler digest change, and rejected unsupported binary downgrade.

`passed:true` means the declared single-profile scenario passed. It is **not**
complete release acceptance when `acceptanceComplete:false` or `gaps` is nonempty.
Publication requires both profile receipts, distinct real boot IDs, the exact
current artifact, the actual committed predecessor and all retention/upgrade
phases, plus rootless coverage in the local-profile receipt. Fast mocked artifact
tests and synthetic version-pair tests cannot replace these receipts.

For diagnosis, a manually dispatched candidate run can select `artifact_run`
from a prior own-repository native candidate run. This skips rebuilding and tests
that same authenticated archive in fresh VMs. GitHub run/source metadata selects
the exact original identity before verification; arbitrary PR or release-workflow
artifacts are refused. Receipts distinguish artifact `sourceCommit` from
`harnessSourceCommit`. Such cross-revision diagnostics are not exact-head release
acceptance: the publication gate requires both to equal the final reviewed source.

## Parent-controlled publication

Before dispatch, the parent must select and review:

1. A new version, its exact clean source commit and a successful maintained
   `.github/workflows/ci.yml` run at that exact commit.
2. A genuine previous native version/artifact from this same release workflow.
   Commit its exact version/source/archive digest in
   [compatibility.json](../../packaging/linux/compatibility.json), with no migration
   and compatible runtime/storage/host ABI. No pair is currently approved.
3. An existing exact release tag and the publisher identity described here.
   Neither workflow creates or moves tags. GitHub must have registered this
   workflow for dispatch; parent-controlled default-branch promotion is not an
   installer or sub-agent side effect.
4. The `native-runtime-publish` GitHub environment with required reviewers.
   The gate refuses publication if that protection is missing. The workflow
   does not silently create an unprotected environment or new signing policy.

A foundation run with `publish=false` may produce a real versioned predecessor
artifact without publishing it or claiming cross-version acceptance. Its
authenticated artifact is retained for 90 days. The next exact reviewed version
can select that run only when its predecessor identity is committed. This avoids
relabeling one binary as two versions or inventing upgrade evidence.

After those decisions, a parent can dispatch the already-reviewed workflow:

```bash
gh workflow run native-runtime-release.yml --repo KirilsTurkins/latent-service-fabric \
  --ref "$APPROVED_VERSION" -f version="$APPROVED_VERSION" \
  -f commit="$APPROVED_COMMIT" -f ci_run="$EXACT_HEAD_CI_RUN" \
  -f predecessor_run="$APPROVED_PREDECESSOR_RUN" -F publish=true
```

Only `workflow_dispatch` is accepted, at the exact tag/commit/version. No PR or
`pull_request_target` event publishes. The build job has attestation permission,
not release-write permission. The final publication job additionally waits for
the required-reviewer environment and both VM jobs, rechecks live exact-head CI,
tag resolution, publisher authentication and receipt identities, and attests the
acceptance documents. It creates one experimental prerelease with `--verify-tag`,
never overwrites an existing release and verifies the uploaded asset digests.
The fixture helper is not a release asset. SBOM and build provenance are inside
the authenticated archive; the complete acceptance receipts and their separate
Sigstore bundle are also release assets.

Publication is a single bounded mutating operation. If it fails after starting,
inspect the selected remote release and `native-publication-result.json` before
any retry. An uncertain or partially uploaded release is not success and is not
automatically overwritten, deleted or retried. Parent review/merges/issue closure
remain separate from this workflow.

## Current recorded boundary

The [compact candidate receipt summary](../evidence/native-runtime-dd08449f.json)
retains scoped results and original receipt hashes, not VM disks or credentials.

- [Run 35449471092](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/35449471092),
  source `dd08449fb2dfb3174bb5468cfd6e13253fe48a17`: the native build and real
  GitHub attestation succeeded. The 444-file archive is 26,469,496 bytes with
  SHA-256 `11000d2dabaa4091e66cee9fc51e02a5754bf8a7a58fecf32e1cc5d4cf88e429`.
  Observed ELF dependencies are `ld-linux-x86-64.so.2`, `libc.so.6`,
  `libgcc_s.so.1` and `libm.so.6`. Independent Windows GitHub CLI verification
  accepted the exact identity, rejected a wrong source commit and checked all
  three signed asset digests; it is not offline Linux proof.
- Both real KVM guests in that run booted Ubuntu kernel `6.8.0-139-generic`,
  Python `3.12.3`, with separately provisioned `gh 2.100.0`. Both passed actual
  offline signature negatives, non-root systemd activation, ordinary/enforced
  bundled echo invocation and same-version protected-identity preservation.
  The local-profile guest additionally changed boot ID from
  `00de0f32-ce27-4ca9-83bf-070b7c9eceb9` to
  `98e6c3ad-6c74-4c9f-9f0e-72e0cabef221` and invoked its retained publication.
  Its recovery test then rejected legitimate catalog hard links. The enforced
  guest hit an SSH timeout at reboot. Both overall receipts are **failures**,
  not complete acceptance; hard-link-safe recovery/purge and bounded read-only
  reboot observation are being corrected.
- [Run 35448259636](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/35448259636),
  source `72c37aa737e13f8b94b22340308d63dc84170d2c`: all 27 focused Linux tests
  passed. Native executables and echo built; archive production failed because
  some crates omit a packaged license. Error-receipt writing also rejected the
  runner's ACL-bearing workspace. This is a failure, not VM evidence.
- The shared-license inventory and isolated host workspace address those observed
  failures without relaxing installed-path checks. Local Windows validation
  passes 13 focused cases and explicitly skips 18 Linux cases. A read-only local
  inventory audit finds 270 dependency packages, 422 license texts and 12 exact
  shared-license mappings; this is not a Linux packaged-artifact test.
- No release version/pair, successful complete VM matrix or published native
  release is claimed by this document. Attach exact new run/receipt identities
  when they exist, and pass the operational boundaries to #237/#238/#240.
