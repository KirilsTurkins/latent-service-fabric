# Optional terminal devcontainer

Use a container for the developer frontend while editing the project on Windows.
The node and guest compilers stay in the explicitly selected Linux workspace.
This path uses the same `latent-dev` commands as Windows/WSL2 and direct Linux;
Docker and an editor extension are not prerequisites for either of those paths.

The exercised environment is Windows x86-64, Docker Desktop 4.86.0 with its
Linux engine 29.7.2, and Dev Container CLI 0.89.0 invoked from a terminal.
The retained [source observation](../development/devcontainer-source-observation.json)
covers packaged frontend startup and three real node starts over SSH, including
authenticated readiness, retained identity, interruption and confirmed shutdown.
Wrong host keys and helper digests were rejected before helper execution. Final
publisher-authenticated candidate and clean-host qualification remain open.

## Prepare reviewed inputs

Choose an already installed container toolchain. This command does not install
Docker, enable virtualization, build an image or start a container. Obtain and
authenticate the selected `linux-x86_64` frontend bundle through
[`dev acquire`](../development/windows-developer-workflow.md#implemented-controller-contracts)
using the independently approved publisher policy, trusted roots and pinned
verifier. Keep the bundle ID returned by that command. A Windows bundle cannot
substitute for a Linux bundle.

From PowerShell, set `$Frontend` to the installed Windows `latent-dev.exe`,
`$State` to its private state directory, `$Project` to the existing capsule
project, and `$Bundle` to that authenticated Linux bundle ID. Paths may contain
spaces or Unicode characters.

```powershell
& $Frontend --state-root $State dev devcontainer --project $Project `
  --bundle $Bundle --consent-files
```

Review the new `.devcontainer` directory. Existing container configuration is
preserved and requires a manual merge. The generator verifies the cache before
copying and hashes each copied file again. An interrupted or changed copy has
an incomplete ownership record and no runnable configuration. These local files
are Git-ignored: each developer generates their own bundle and volume identity.
They are excluded from guest source snapshots and build recipes.

The Dockerfile pins its Ubuntu base and certificate bootstrap images by digest,
uses the reviewed Ubuntu package snapshot, and pins Git, OpenSSH and certificate
package versions. It verifies every redistributed frontend, helper, inventory
and license file during the image build. The image contains the frontend's
embedded Python; it does not need a separately installed Python interpreter.

Building needs the selected OCI images and signed Ubuntu snapshot packages.
For offline use, build and retain the image in the controlled environment first;
an absent input fails instead of downloading a replacement version. Guest tool
bundles and runtime inputs remain separate authenticated selections. A later
SSH connection still requires connectivity to the chosen Linux host.

## Start deliberately from the terminal

Provision Node.js and the reviewed Dev Container CLI separately. The executed
CLI archive was `@devcontainers/cli` 0.89.0 from the
[official npm registry](https://registry.npmjs.org/@devcontainers/cli/-/cli-0.89.0.tgz),
with this SHA-512 value in Base64:

```text
LzaoOGKQ/Zql6PsiZ4hVIYVZagzWkD65aG/1ou5/Kly5Y1PtjLg1yn7qu+LZCzVoAl6DZZ/pbz8qOO4RLNlqMg==
```

Verify that archive against the reviewed value before extracting it. Set
`$DevContainerCli` to its extracted `package/devcontainer.js` and `$CliState` to
a dedicated CLI state directory outside the project. Then build and start:

```powershell
$Started = & node $DevContainerCli up --workspace-folder $Project `
  --mount-workspace-git-root false --skip-post-create `
  --user-data-folder $CliState | ConvertFrom-Json
if ($LASTEXITCODE -ne 0 -or $Started.outcome -ne 'success') {
  throw 'Devcontainer startup failed; inspect its retained output.'
}
$Container = $Started.containerId
& node $DevContainerCli exec --container-id $Container `
  --workspace-folder $Project --user-data-folder $CliState `
  /opt/latent-dev/bin/latent-dev dev doctor
```

The container runs as UID/GID 10001 with dropped Linux capabilities, no new
privileges and finite memory, CPU and process limits. Its only mounts are this
project at `/workspaces/project` and its generated private home volume at
`/home/latent-dev`. There is no host Docker socket, host home/root mount,
automatic task, environment probe or forwarded port. Keep the editor on the host
and run the printed CLI commands in its terminal.

This declared path does not attach VS Code's Dev Containers extension. That
extension has its own
[Git credential and SSH-agent sharing behavior](https://code.visualstudio.com/remote/advancedcontainers/sharing-git-credentials),
which is outside the terminal CLI observation. The generated environment disables
ambient SSH-agent and global Git configuration use; it contains no credentials.

## Connect to the chosen Linux node

`127.0.0.1` inside the devcontainer is the devcontainer itself. The Linux node's
management listener stays on that Linux host's loopback. The explicit SSH
backend runs the verified helper on that host; it does not expose or forward the
management listener. Select a hostname reachable from the container and verify
its SSH host key through a separate trusted channel.

Provision a dedicated SSH key and known-hosts file inside the private container
home. Install only its public key in the selected Linux user's authorized keys.
Keep that user's runtime, build tools, outputs, tokens and node state in the
private Linux workspace. Do not put these files in the project mount.

The backend document has the same
[explicit SSH fields](../development/windows-developer-workflow.md#project-transfer-and-test-boundaries)
as the ordinary frontend. Its `identityFile` and `knownHosts` paths are inside
the container; `ssh` is `/usr/bin/ssh`. Select the exact helper digest installed
on the Linux host. With that document at `/home/latent-dev/ssh-backend.json`:

```powershell
& node $DevContainerCli exec --container-id $Container `
  --workspace-folder $Project --user-data-folder $CliState `
  /opt/latent-dev/bin/latent-dev dev connect --workspace my-project `
  --backend-config /home/latent-dev/ssh-backend.json
& node $DevContainerCli exec --container-id $Container `
  --workspace-folder $Project --user-data-folder $CliState `
  /opt/latent-dev/bin/latent-dev dev up --workspace my-project
```

`up` stays in the foreground. In another terminal, use the same CLI prefix for
`dev status`, `dev logs`, `dev build`, `dev test --environment node` and
`dev down`, with the explicit workspace. Project arguments inside the container
use `/workspaces/project`. Recipe trust, six-language tool installation,
source synchronization, watch and uncertain-operation recovery use the existing
controller; the container introduces no second build or node lifecycle.

## Stop and retain state

Run `dev down --workspace my-project` through the same CLI prefix and check its
`stopped`, `reaped` and `cleanShutdown` result. The foreground command should
also exit. Inspect `dev status` or recover the original operation if transport
was lost; closing a terminal or stopping the container does not establish that
the remote node stopped.

After confirmed node cleanup, `docker stop $Container` stops that exact
container. The generated home volume retains frontend state and explicit SSH
credentials across container restarts. Node data and compiler caches stay on
the Linux host. Removing a container or its home volume does not purge the
remote workspace. Follow the core workflow's separate, explicitly confirmed
purge operation before deliberately removing any retained state.
