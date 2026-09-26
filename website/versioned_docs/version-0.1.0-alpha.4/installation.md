# Install or build LSF

Choose the **developer toolkit** to create and test an application, or the
**native Linux runtime** for a persistent standalone server. Both are distributed
with [0.1.0-alpha.4](https://github.com/KirilsTurkins/latent-service-fabric/releases/tag/0.1.0-alpha.4).
The developer toolkit includes a disposable test node and six compiler choices;
the server runtime has its own installer, security profiles and systemd service.
The historical `0.1.0-alpha.3` release is source-only.

## Choose your starting point

| What you want to do | Follow this guide |
| --- | --- |
| Create and test a local application | [Get the developer tools](start/developer-setup.md), then [application development](start/application-development.md) |
| Install a persistent Linux server | [Native installation below](#install-the-native-runtime) |
| Build and inspect LSF itself | [Run your first node from source](start/first-node.md) |
| Write a capsule after starting a node | [Create a capsule](component-development/creating-a-capsule.md) |
| Connect an existing application | [Use a client SDK](learn/use-a-client.mdx) |
| Serve a static or Angular website | [Static sites](component-development/static-sites.md) or [Angular walkthrough](learn/build-and-deliver-angular.mdx) |
| Change LSF itself | [Contribute](contribute/index.md) and [install the contributor toolchain](development/toolchain.md) |

Running an SDK client does not install or start the node. Start one node first,
then use its local connection profile in your application. Management RPCs stay
on loopback; for a remote server, use a local SSH session. Application HTTP
traffic uses a separately configured [HTTP listener](reference/http-ingress.md).

## Native installation requirements

The native installer targets **Ubuntu Server 24.04 on x86_64**, with kernel 6.8+,
glibc 2.39+, SSE2 and Python 3.12+. It checks filesystem locking/synchronization,
protected files, dynamic libraries and host pressure observations under the
intended node identity. External capsule execution also needs the approved
Landlock ABI 3/seccomp compiler sandbox.

The release includes authenticated acceptance receipts for the published
archive: local and enforced profiles, reboot, retained deployment, recovery and
the explicitly supported upgrade pair. Older
[rehearsal records](evidence/native-upgrade-35821200294/README.md) keep their own
source and artifact identities; they do not qualify newer builds. Current runtime execution and security limits are described in
[execution profiles](runtime/execution-security-profiles.md).

No container runtime is required for native installation. OCI registries distribute
application packages independently of how you install LSF itself.

## Install the native runtime

Download the archive, `release.json`, `lsf-install.pyz`, `SHA256SUMS` and
`SHA256SUMS.sigstore.json` from the selected release. Do not use the `dev-native-`
assets for a server: those belong to the disposable development toolkit.

The [bundled installation instructions](../packaging/linux/INSTALL.md) cover the
complete procedure, including exact command syntax and verification inputs:

1. [Verify the publisher and bundle](../packaging/linux/INSTALL.md#prerequisites-and-independent-bootstrap-trust)
   before running downloaded code. Obtain trust roots and the approved identity
   policy independently of the bundle.
2. Choose [rootless evaluation](../packaging/linux/INSTALL.md#rootless-evaluation)
   for a foreground process in private user-owned directories, or
   [persistent server installation](../packaging/linux/INSTALL.md#persistent-server)
   for a non-root systemd service.
3. Configure the selected profile and credentials, start the node, and check
   [authenticated readiness](../packaging/linux/INSTALL.md#status-drain-and-hardening).
4. [Deploy and invoke the bundled example](../packaging/linux/INSTALL.md#first-retained-invocation)
   before delivering your own applications.
5. Use [consistent backups and recovery](../packaging/linux/INSTALL.md#reinstall-upgrade-and-recovery)
   when changing installations. Check the declared upgrade pair before upgrading.

The installer does not configure public management access, firewall rules,
reverse proxies, application HTTP ingress or clusters. One service owns the node
and its transient compiler children; it does not create a service process per
capsule.

[Removal and purge](../packaging/linux/INSTALL.md#removal-and-separately-confirmed-purge)
are separate operations. Review the retained data and backup requirements before
choosing destructive purge.

## Building a native release

Maintainers use the [native release gate](development/native-release-gate.md).
It requires a clean reviewed source, matching package versions, real VM checks
for the exact archive, independent publisher verification and explicit publication
approval. Building a candidate or passing ordinary CI does not publish a release.
