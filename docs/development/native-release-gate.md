# Native release gate

This is the maintainer gate for [native standalone installation](../installation.md)
and [#308](https://github.com/KirilsTurkins/latent-service-fabric/issues/308), not a
claim that a binary release or its full acceptance evidence already exists.
The parent integrator chooses the final reviewed commit and new version only
after exact-head CI. Do not move the historical source-only `0.1.0-alpha.3` tag.

## Current-format native foundation

The immutable `0.1.0-alpha.4-rc.2` foundation identifies source
`a53b7b219a46f6ca91ae7bc7830669f8aa4bbe2e`. Its exact-source
[CI run 35807320818](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/35807320818)
and [nonpublishing release run 35811188306](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/35811188306) passed. Both clean-VM profiles
used the release-workflow/tag identity and the same authenticated archive;
the [retained receipt](../evidence/native-foundation-35811188306.json) records its SHA-256,
real boot IDs, receipt hashes and independent publisher verification.

The distinct `0.1.0-alpha.4` source declares only that observed foundation in
[`compatibility.json`](../../packaging/linux/compatibility.json). Both versions
use current publication-aware catalog formats and HTTP table/receipt format 2.
Installer and node configuration format 1 remain current. No obsolete storage
reader or migration is restored for this compatible pair.

The earlier immutable `0.1.0-alpha.4-rc.1` tag identifies source
`010c1c0605533a9f8a51a36e8b45265baa6255bb`. Its maintained CI passed in
[run 35757424832](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/35757424832),
and [nonpublishing release run 35763422270](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/35763422270)
passed both clean-VM profiles. Its
[retained receipt](../evidence/native-foundation-35763422270.json) keeps that
historical evidence and the unfulfilled compatible-pair criterion. This source
can write obsolete HTTP table format 1 and is no longer a declared predecessor.
Do not move its tag, rewrite its receipts or reinstate a legacy storage reader.

The foundation remains unpublished and honestly reports
`acceptanceComplete:false`: it has no selected predecessor of its own. Its
single-profile success does not complete #308. The final `0.1.0-alpha.4` source
must pass its own exact-source CI and real compatible-upgrade/unsupported-downgrade
checks against these actual rc.2 bytes. Complete same-source receipts and the
protected publication approval remain required before a runtime release exists.

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
   and compatible runtime/storage/host ABI. The committed rc.2 predecessor
   identifies the selected pair; its final VM qualification is still required.
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

The [successful diagnostic receipt summary](../evidence/native-runtime-3925d416.json)
retains exact source/archive identities, original receipt hashes and real boot
IDs, not VM disks, keys or credentials. [Run 35451109956](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/35451109956)
passed both fresh KVM Ubuntu guests, including the local profile's actual
unprivileged rootless foreground/removal/purge phase. Both server profiles passed
real reboot, retained invocation, stopped backup/recovery, removal/reinstall and
separately confirmed purge. The guest kernel was `6.8.0-139-generic`, Python
`3.12.3`, and the separately provisioned verifier was `gh 2.100.0`.

This diagnostic deliberately reuses the authenticated native archive from
[run 35450192265](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/35450192265),
source `260c3e4ef14a8afe0818ce9a9ed56f05c3833b17`, SHA-256
`1f14b0cdd4669d062437959a404befe9e4383d24d70d25b9d5ae2f8bb9f2ed9e`.
Its harness is `3925d4163f0a7af12ce2541d23fa5c09d4fc2856`; the later change
keeps rootless operator inputs outside the managed prefix rather than weakening
the installer's untracked-file rejection. The complete maintained
[CI run 35450998693](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/35450998693)
also passed at that harness commit. Neither cross-revision diagnostics nor an
earlier green CI result qualify a later release commit.

### Acceptance handoff

| Boundary | Observed result and remaining qualification |
| --- | --- |
| Real native bundle, SBOM, provenance and licenses | Built and GitHub-attested candidate, not a release-tagged published runtime. |
| Authentication before downloaded bootstrap | Real offline candidate identity verification and tamper/unsigned/wrong-repository/wrong-commit rejection in both guests; release-workflow/tag identity still requires its own run. |
| Explicit profiles and non-root systemd readiness | Both local Wasmtime and enforced isolated AOT pass without sandbox fallback, public bind or reusable fixture credentials. |
| Protected identities and repeat installation | Actual credential/key rejection, preserved configuration/credentials/AOT key/publication and same-version PID preservation pass. Missing external trust leaves installation unactivated and resumes with the same key. |
| Real reboot and retained deployment | Both guests change boot ID and invoke the same retained publication without republishing. |
| Backup, recovery, removal and purge | Both profiles pass stopped consistent backup/full-set restore, default retention/reinstall, exact-installation purge and unsafe-path refusal. |
| Rootless evaluation | UID 1000 foreground invocation, live-removal `installation-busy` refusal, clean shutdown, removal and purge pass without a user systemd service. |
| Cross-version compatibility | **Not exercised in a real VM:** no genuine declared predecessor is selected. Compatible upgrade and unsupported binary downgrade are implemented but remain release gates, not covered by same-version reinstall or mocked tests. |
| Final source, release identity and publication | **Parent-controlled, not performed:** select new versions/commits, register the release workflow, configure required reviewers, obtain exact-head CI and complete same-source release receipts, then publish. |

Both successful diagnostic receipts explicitly contain `acceptanceComplete:false`
and `declared-compatible-native-version-pair-not-yet-selected`. The publication
gate also refuses their artifact/harness mismatch. As inspected on 2026-09-19,
the release-workflow and `native-runtime-publish` environment API lookups returned
404; OAuth workflow scope is available and is **not** a remaining push blocker.
Do not create a trust policy, move a historical tag, or mark #308 complete to
work around those parent decisions.

### Earlier failures and fixes

- [Run 35449471092](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/35449471092),
  source `dd08449fb2dfb3174bb5468cfd6e13253fe48a17`, produced a real attested
  444-file, 26,469,496-byte archive. Its
  [historical receipt summary](../evidence/native-runtime-dd08449f.json) retains
  the archive identity, independent Windows verification and both failed VM
  receipts. Local reboot passed before legitimate CAS hard links broke backup;
  the external guest timed out at reboot. These failures are not rewritten.
- `260c3e4ef14a8afe0818ce9a9ed56f05c3833b17` preserves verified contained CAS
  hard-link sets through backup/purge and rejects outside references before any
  deletion. Protected config/trust/executable reads still require single links.
  It submits reboot once and uses bounded read-only observation after an
  uncertain SSH response. Both real server lifecycles then passed; the remaining
  rootless removal failure correctly rejected a harness-created untracked input
  inside the installation prefix. `3925d416` fixes that test input location.
- Earlier native build failures from missing upstream license texts and runner
  ACLs were corrected with the exact shared-license inventory and private host
  workspace, without relaxing installed-path protection. All 37 focused Linux
  tests passed in run `35450192265`. The fast suite at `3925d416` also runs
  37 cases; Windows passes 16 and explicitly skips 21 Linux-only cases. Windows
  tests never substitute for packaged-artifact Linux evidence.

Pass these scoped successes and remaining release gates to #237/#238/#240.
Operator documentation and its default-branch/Wiki promotion can proceed with
this honest candidate boundary; #240's phase acceptance is not a circular
prerequisite for publishing documentation. Actual native release/tag publication
remains separate and parent controlled.
