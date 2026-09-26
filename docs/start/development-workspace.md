# Set up your development workspace

Create the place where your capsule will be compiled and run. Your application
files stay in your project folder. LSF keeps the node, compiler and credentials
in separate private storage. You can stop the node and return to the same work later.

First [get the developer tools](developer-setup.md) for your chosen language.
Use **Windows** or **Linux** below, then continue to the same
[Creating a capsule](../component-development/creating-a-capsule.md) tutorial.
Windows uses WSL2 for the compiler and node; you still edit files and run commands
from PowerShell. This creates an LSF application, regardless of your desktop OS.

The examples use a new project named `My greeting`, workspace `test-my-greeting`
and port `18080`. Choose a different project and workspace name for another example;
choose another port if you want both nodes running together. Use the same language
identifier you downloaded: `rust`, `c`, `typescript`, `go`, `java` or `dotnet` (C#).

## If you use Windows

### Open your working terminal

Open PowerShell and run this once in that terminal. The `dev` function is a short
form of `latent-dev --state-root ... dev`; it supplies your tool and state paths
and stops on a failed command. Keep this terminal open for the tutorial.

```powershell
$Inputs = Join-Path $env:USERPROFILE 'LSF-inputs-alpha4'
$Language = 'rust' # Use the language you downloaded.
$Frontend = Join-Path $Inputs 'frontend/bin/latent-dev.exe'
$State = Join-Path $env:LOCALAPPDATA 'LatentDev-tutorial'
$Project = Join-Path $env:USERPROFILE 'Projects\My greeting'
$Workspace = 'test-my-greeting'
$WindowsVerifier = (Get-Command gh.exe).Source
$WindowsVerifierSha256 = 'sha256:' + (Get-FileHash -LiteralPath $WindowsVerifier -Algorithm SHA256).Hash.ToLowerInvariant()
$LinuxVerifierSha256 = 'sha256:' + (Get-FileHash -LiteralPath (Join-Path $Inputs 'gh-linux') -Algorithm SHA256).Hash.ToLowerInvariant()
$DeveloperPolicy = Join-Path $Inputs 'developer-policy.json'
$RuntimePolicy = Join-Path $Inputs 'native-policy.json'
$TrustedRoot = Join-Path $Inputs 'trusted_root.jsonl'
$Policy = Get-Content -LiteralPath $DeveloperPolicy -Encoding UTF8 | ConvertFrom-Json
$Version = $Policy.version

function dev {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$DevArguments)
    & $Frontend --state-root $State dev @DevArguments
    if ($LASTEXITCODE -ne 0) { throw 'The command failed. Inspect its output before continuing.' }
}

dev doctor
$Admission = if ($Language -in @('rust','c')) { 'trusted-local' } else { 'signed-fixture' }
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Project) | Out-Null
```

Expect doctor to report the available prerequisites. WSL2 and virtualization must
already work. Keep `$State` in private local storage outside the project; let the
frontend create it with the required permissions.

### Create the Linux environment once

On your first setup, authenticate and import the supplied WSL image:

```powershell
$WslBundle = (dev acquire --bundle-directory (Join-Path $Inputs 'wsl') `
    --publisher-policy $DeveloperPolicy --trusted-root $TrustedRoot `
    --verifier $WindowsVerifier --verifier-sha256 $WindowsVerifierSha256 `
    --version $Version --target linux-x86_64-wsl-rootfs --allow-candidate | ConvertFrom-Json).result
$WslInventory = Get-Content -LiteralPath (Join-Path $State "bundles\$($WslBundle.bundle)\rootfs-inventory.json") `
    -Encoding UTF8 | ConvertFrom-Json
$Distro = (dev provision --bundle $WslBundle.bundle --consent-provision | ConvertFrom-Json).result
```

This creates one LSF-owned distro, leaving your other distros alone. Save its
returned name. For another workspace in the same `$State`, **skip the provision
command**: run `dev wsl-status` to inspect the existing distro and reuse the
verified `$WslInventory` from this terminal.

### Create a workspace and install its tools

```powershell
dev wsl-workspace --workspace $Workspace --helper-sha256 $WslInventory.helperSha256
$Utf8 = [Text.UTF8Encoding]::new($false)
$RuntimeInputs = Join-Path $Inputs 'tutorial-runtime.json'
$ToolInputs = Join-Path $Inputs "tutorial-$Language-tools.json"
$Common = @{
    version = $Version; trustedRoot = $TrustedRoot
    verifier = (Join-Path $Inputs 'gh-linux'); verifierSha256 = $LinuxVerifierSha256
    allowCandidate = $true; consent = $true
}
$Runtime = $Common.Clone()
$Runtime.schemaVersion = 'latent.dev.install-inputs.v1'
$Runtime.releaseDirectory = Join-Path $Inputs 'native'
$Runtime.publisherPolicy = $RuntimePolicy
$Runtime.profile = 'local-experimental-v1'
$Runtime.port = 18080
$Tools = $Common.Clone()
$Tools.schemaVersion = 'latent.dev.tool-inputs.v1'
$Tools.bundleDirectory = Join-Path $Inputs $Language
$Tools.publisherPolicy = $DeveloperPolicy
$Tools.language = $Language
[IO.File]::WriteAllText($RuntimeInputs, ($Runtime | ConvertTo-Json), $Utf8)
[IO.File]::WriteAllText($ToolInputs, ($Tools | ConvertTo-Json), $Utf8)
dev install --workspace $Workspace --runtime-inputs $RuntimeInputs
dev install-tools --workspace $Workspace --tool-inputs $ToolInputs
```

The workspace has its own Linux user and private node credentials. The two input
files contain paths and public verification settings; you do not write tokens.
Expect each command to finish with `code: success`.

## If you use Linux

Use Ubuntu 24.04 x86-64, Linux 6.8 or newer, and Python 3.13.5 installed at
`/usr/local/bin/python3.13`. Run as your ordinary account. The downloaded frontend
contains the helper; the helper's pinned interpreter is a separate host prerequisite.

Open Bash and run this once. It creates installation settings from the downloaded
toolkit, selects this host, and installs the node and your compiler into the workspace.
The `dev` function supplies the frontend and private state paths in later examples.

```bash
set -euo pipefail
umask 077
export Inputs="$HOME/LSF-inputs-alpha4"
export Language=rust
Frontend="$Inputs/frontend/bin/latent-dev"
State="$HOME/.latent-dev-tutorial"
Workspace=test-my-greeting
Project="$HOME/Projects/My greeting"
Admission=signed-fixture
if [[ "$Language" == rust || "$Language" == c ]]; then Admission=trusted-local; fi
mkdir -p "$HOME/Projects"
python3 - <<'PY'
import hashlib, json, os, pathlib, shutil
root = pathlib.Path(os.environ['Inputs'])
language = os.environ['Language']
assert language in ('rust', 'c', 'typescript', 'go', 'java', 'dotnet')
manifest = json.loads((root/'linux/developer-bundle.json').read_text())
helper = next(file for file in manifest['files'] if file['path'] == 'helper.pyz')
verifier = root/'gh-linux'
shutil.copyfile(shutil.which('gh'), verifier)
verifier.chmod(0o700)
identity = 'sha256:'+hashlib.sha256(verifier.read_bytes()).hexdigest()
def save(name, value):
    (root/name).write_text(json.dumps(value)+'\n')
save('direct-backend.json', dict(kind='linux', helperSha256=helper['sha256'],
     python='/usr/local/bin/python3.13', helper=str(root/'frontend/helper.pyz')))
common = dict(version=manifest['version'], trustedRoot=str(root/'trusted_root.jsonl'),
              verifier=str(verifier), verifierSha256=identity, allowCandidate=True, consent=True)
save('tutorial-runtime.json', dict(common, schemaVersion='latent.dev.install-inputs.v1',
     releaseDirectory=str(root/'native'), publisherPolicy=str(root/'native-policy.json'),
     profile='local-experimental-v1', port=18080))
save('tutorial-tools.json', dict(common, schemaVersion='latent.dev.tool-inputs.v1',
     bundleDirectory=str(root/language), publisherPolicy=str(root/'developer-policy.json'), language=language))
PY
dev() { "$Frontend" --state-root "$State" dev "$@"; }
dev doctor
dev connect --workspace "$Workspace" --backend-config "$Inputs/direct-backend.json"
dev install --workspace "$Workspace" --runtime-inputs "$Inputs/tutorial-runtime.json"
dev install-tools --workspace "$Workspace" --tool-inputs "$Inputs/tutorial-tools.json"
```

Expect `code: success` for the connection and both installations. The private
credentials are generated for you. Two workspaces under the same Linux account
do not protect data from that account; use separate accounts when that matters.

## Continue with your application

Keep the terminal and its variables. Open [Creating a capsule](../component-development/creating-a-capsule.md)
to create the project, read its code, build it, and send the first request. The
remaining development commands are the same on Windows and Linux.

Rust and C use the explicit `trusted-local` profile for your own disposable
development code, allowing an edit/build/deploy loop. The other languages use
`signed-fixture` with the runtime permissions required by their compiler. That
fixture approves one build for 30 minutes. Use a fresh disposable workspace for
a changed build or expired fixture; this toolkit is not a production signing service.

If a port is occupied, select another port in the runtime input before installing
a new workspace. LSF does not stop another process to claim its port. For command
help, failed builds, lost responses and cleanup, use [Developer commands](../how-to/developer-commands.md).

## Use a remote Linux host instead


The administrator supplies a dedicated unprivileged account, its private SSH
identity file, and an independently verified known-hosts file. The remote helper
must be installed at `/opt/latent-dev/helper.pyz`, with Python 3.13.5 at
`/usr/local/bin/python3.13`. Keep the private identity outside the application
source. An unknown or changed host key fails before the helper runs.

On Windows, this reviewed backend selection uses the Windows OpenSSH client:

```json
{
  "kind": "ssh",
  "helperSha256": "sha256:REPLACE_WITH_SELECTED_HELPER_DIGEST",
  "host": "dev.example.test",
  "port": 22,
  "user": "lsfdev",
  "identityFile": "C:\\LSF Private\\id_ed25519",
  "knownHosts": "C:\\LSF Private\\known_hosts",
  "ssh": "C:\\Windows\\System32\\OpenSSH\\ssh.exe"
}
```

Replace the example host, account and paths with the supplied ones. Save it
outside the project and connect explicitly:

```powershell
& $Frontend --state-root $State dev connect --workspace test-remote-greeting `
    --backend-config 'C:\LSF Private\ssh-backend.json'
```

Then use the same install, install-tools, init, trust and application commands
with that workspace name. The input documents refer to files on the **client**;
the controller transfers only the selected bytes before verifying/installing on
the remote host. Node management binds the remote loopback interface. Client
loopback is a different network namespace; no public management bind or tunnel
is assumed.

On a Linux client, select `/usr/bin/ssh` and absolute Linux identity/known-hosts
paths in the same JSON schema. SSH uses strict host-key checking, the one
selected identity, no agent forwarding, no proxy command and finite connection
deadlines. A lost SSH connection leaves remote cleanup unconfirmed: restore the
connection, inspect status and recover the original pending operation. Do not
repeat an uncertain invocation.

`dev down` retains the remote workspace. `dev purge --confirm-workspace NAME`
removes only that owned workspace after confirmed cleanup; it does not remove
the remote account, SSH server, host, or another workspace. The
[optional devcontainer](../component-development/devcontainer.md) is another client for this same adapter.
