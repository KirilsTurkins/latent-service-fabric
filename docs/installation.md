# Native standalone installation

**Delivery status:** native packaging and fail-closed installer work for
[#308](https://github.com/KirilsTurkins/latent-service-fabric/issues/308).
This page is not a claim that a publisher-authenticated binary release or its
clean-VM acceptance evidence has been published. The historical
[`0.1.0-alpha.3` release](https://github.com/KirilsTurkins/latent-service-fabric/releases/tag/0.1.0-alpha.3)
remains source-only. Do not install an unsigned candidate as an authenticated
release or infer production/hostile-multitenant certification.

## Choose the right path

| Need | Entry point |
| --- | --- |
| Install a prebuilt native runtime | [Bundled operator instructions](../packaging/linux/INSTALL.md#prerequisites-and-independent-bootstrap-trust): verify the publisher before executing downloaded code. |
| Try controlled workloads without root | [Rootless foreground evaluation](../packaging/linux/INSTALL.md#rootless-evaluation): private user-owned files, no system service. |
| Run a persistent single server | [Server installation](../packaging/linux/INSTALL.md#persistent-server): non-root node, protected credentials, explicit profile/start/enablement. |
| Develop an application/capsule | [Guest SDK](component-development/guest-sdk.md) and [operator CLI](reference/operator-cli.md); this does not install the node runtime. |
| Build or contribute to LSF itself | [Pinned toolchain](development/toolchain.md) and [development quickstart](development/standalone-quickstart.md), not a server installer. |

The narrow first candidate matrix is Ubuntu Server 24.04/x86_64, kernel 6.8+,
glibc 2.39+, SSE2 and Python 3.12+. Actual pressure observations, local filesystem
locking/directory synchronization, protected-file semantics, dynamic libraries
and, for external capsules, the approved Landlock ABI 3/seccomp compiler are
checked under the intended node identity. Until the packaged-artifact VM gate
passes, this is the **candidate** support matrix, not a tested-platform claim.
There is no container-runtime prerequisite or alternative container installation
mode. Capsule OCI transport remains independent of native runtime distribution.

## Authority and operation

- [Bootstrap verification and offline inputs](../packaging/linux/INSTALL.md#prerequisites-and-independent-bootstrap-trust)
- [Explicit security profiles](runtime/execution-security-profiles.md), [protected files](runtime/protected-configuration.md), [isolated AOT](runtime/trusted-aot.md)
- [Protected layout and credentials](../packaging/linux/INSTALL.md#layout-and-credentials)
- [First retained invocation and publication references](../packaging/linux/INSTALL.md#first-retained-invocation)
- [Authenticated readiness, logs and drain](../packaging/linux/INSTALL.md#status-drain-and-hardening)
- [Compatibility, consistent backups and recovery](../packaging/linux/INSTALL.md#reinstall-upgrade-and-recovery)
- [Removal versus destructive purge](../packaging/linux/INSTALL.md#removal-and-separately-confirmed-purge)

Management remains loopback-only over a local SSH session. Installation does not
configure public management, firewall rules, reverse proxies, TLS bypasses,
clusters, or [application HTTP ingress](reference/http-ingress.md). One systemd
service owns the native node and its transient compiler children, not deployed
capsules. Fixed node runtime plus active activations plus bounded shared caches
and catalog metadata remains the resource model.

## Maintainer build and release boundary

The native builder requires a clean checkout at the exact explicit commit, the
committed lockfile, the pinned Rust/wasm-tools versions and Ubuntu 24.04. It builds
the three native executables and the maintained echo component, inventories ELF
dependencies/GLIBC requirements, bundles dependency license texts, generates SPDX
and observed in-toto/SLSA-format provenance, and verifies the assembled archive.
It does not claim a SLSA assurance level or cross-host reproducibility.

```bash
python3 tools/build_native_runtime.py --commit "$REVIEWED_COMMIT" \
  --version "$RELEASE_VERSION" --output "$PWD/target/native-release/$RELEASE_VERSION"
python3 -m unittest tools.tests.test_native_runtime
```

Version must match the committed workspace version. A new binary release needs a
new parent-reviewed release identity; do not reuse the historical alpha.3 tag.
The [maintainer release gate](development/native-release-gate.md) describes the
exact workflow, required review environment, two-profile real-VM matrix and
compatible-version selection. It distinguishes scoped candidates from complete
release acceptance and records observed failures without claiming a reboot test.
The builder emits an **unsigned candidate**. The release gate uses GitHub artifact
attestations with the exact repository, `native-runtime-release.yml` workflow,
release tag, source/signing commit and GitHub-hosted runner certificate identity.
Operators separately provision GitHub CLI, Sigstore roots and the approved
identity policy before executing any downloaded bootstrap. No project bootstrap
key, invented fingerprint or bundle-provided trust root is needed. The parent
chooses the final version/commit only after exact-head CI and acceptance review;
publication must not precede that gate. Capsule signing/admission is a separate policy.

The signed `SHA256SUMS` binds exactly the archive, `release.json`, and
`lsf-install.pyz`. The manifest also binds every archive file's name, mode, size
and SHA-256, the source/lockfile/toolchain, runtime/host ABI and approved compiler.
The installer re-verifies using independently installed `gh`, an offline
attestation bundle and separately supplied trusted roots, then pins the opened
archive through extraction. No installation command downloads a branch or invokes
a development compiler. The approved isolated AOT compiler runs only for the
selected profile's maintained readiness probe and actual capsule preparation.

## Evidence and downstream handoff

The fast Python suite is selected by the existing contracts job's
`unittest discover -s tools/tests` under the maintained
[full CI profile](development/ci-profiles.md). It distinguishes synthetic artifact
and mocked lifecycle tests from actual native execution. Windows skips Linux
descriptor/lifecycle cases; a Windows result cannot establish them. Mocked `gh`
unit tests check argument/identity and failure handling, not Sigstore cryptography.
Real release acceptance must additionally retain:

1. Exact reviewed source, build/toolchain, workflow/certificate and archive identities.
2. A fresh Ubuntu VM without source, Rust, a guest compiler or a container runtime.
3. Packaged-binary local and enforced-profile checks, authenticated readiness and
   a retained publish/deploy/invoke using the bundled component.
4. Actual changed boot ID after reboot and an invocation of the retained deployment.
5. Same-version key/config/credential/catalog preservation, one declared and
   genuinely exercised compatible version pair, incompatible-upgrade rejection.
6. Remove/reinstall recovery, separate exact-installation purge, and a real
   unprivileged rootless foreground run.

No compatible cross-version pair is currently approved in
[`packaging/linux/compatibility.json`](../packaging/linux/compatibility.json).
Publisher approval, real prebuilt artifact production and the complete VM/reboot
matrix are explicit release gates, not boxes checked by writing a test driver.
Supply exact receipts and these operational boundaries to #237/#238/#240; preserve
the historical release and benchmark identities when producing operator/Wiki coverage.
