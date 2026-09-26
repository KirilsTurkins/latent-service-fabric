# Set up your development workspace

Create the place where your capsule will be compiled and run. Your application
files stay in your project folder; the node, compiler and credentials use separate
private storage. First [get the developer tools](developer-setup.md).

Save the setup file for your OS to **Downloads**. It prepares the existing `dev`
commands, installs your selected tools and reads the template settings for you.
You only choose your language, project and workspace; you do not assemble JSON
files or copy hashes. Keep this terminal open for the capsule tutorial.

The default project is `Projects/My greeting` in your home folder, the workspace
is `test-my-greeting`, and the node uses port `18080`.

## If you use Windows

Use PowerShell on Windows x86-64 with working WSL2 and virtualization. Your editor
and commands stay on Windows; the compiler and node run in the LSF-owned distro.

<!-- lsf-download: setup-lsf-workspace.ps1 -->

```powershell
param(
    [ValidateSet('rust','c','typescript','go','java','dotnet')][string]$Language = 'rust',
    [ValidatePattern('^test-[a-z0-9][a-z0-9-]*$')][string]$Workspace = 'test-my-greeting',
    [string]$Project = (Join-Path $env:USERPROFILE 'Projects\My greeting'),
    [ValidateRange(1024,65535)][int]$Port = 18080,
    [string]$Inputs = (Join-Path $env:USERPROFILE 'LSF-inputs-alpha4'),
    [string]$State = (Join-Path $env:LOCALAPPDATA 'LatentDev-tutorial'),
    [switch]$Provision,
    [switch]$SessionOnly
)
$ErrorActionPreference = 'Stop'
$Frontend = Join-Path $Inputs 'frontend/bin/latent-dev.exe'
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

if ($SessionOnly) { return }
dev doctor
$Admission = if ($Language -in @('rust','c')) { 'trusted-local' } else { 'signed-fixture' }
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Project) | Out-Null

$WslBundle = (dev acquire --bundle-directory (Join-Path $Inputs 'wsl') `
    --publisher-policy $DeveloperPolicy --trusted-root $TrustedRoot `
    --verifier $WindowsVerifier --verifier-sha256 $WindowsVerifierSha256 `
    --version $Version --target linux-x86_64-wsl-rootfs --allow-candidate | ConvertFrom-Json).result
$WslInventory = Get-Content -LiteralPath (Join-Path $State "bundles\$($WslBundle.bundle)\rootfs-inventory.json") `
    -Encoding UTF8 | ConvertFrom-Json
if ($Provision) {
    dev provision --bundle $WslBundle.bundle --consent-provision
} else {
    dev wsl-status
}

dev wsl-workspace --workspace $Workspace --helper-sha256 $WslInventory.helperSha256
$Utf8 = [Text.UTF8Encoding]::new($false)
$RuntimeInputs = Join-Path $Inputs "$Workspace-runtime.json"
$ToolInputs = Join-Path $Inputs "$Workspace-$Language-tools.json"
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
$Runtime.port = $Port
$Tools = $Common.Clone()
$Tools.schemaVersion = 'latent.dev.tool-inputs.v1'
$Tools.bundleDirectory = Join-Path $Inputs $Language
$Tools.publisherPolicy = $DeveloperPolicy
$Tools.language = $Language
[IO.File]::WriteAllText($RuntimeInputs, ($Runtime | ConvertTo-Json), $Utf8)
[IO.File]::WriteAllText($ToolInputs, ($Tools | ConvertTo-Json), $Utf8)
dev install --workspace $Workspace --runtime-inputs $RuntimeInputs
dev install-tools --workspace $Workspace --tool-inputs $ToolInputs

$Templates = (dev acquire --bundle-directory (Join-Path $Inputs $Language) `
    --publisher-policy $DeveloperPolicy --trusted-root $TrustedRoot `
    --verifier $WindowsVerifier --verifier-sha256 $WindowsVerifierSha256 `
    --version $Version --target linux-x86_64 --allow-candidate | ConvertFrom-Json).result
$Bundle = $Templates.bundle
$Index = Get-Content -LiteralPath (Join-Path $State "bundles/$Bundle/templates.json") -Raw | ConvertFrom-Json
$GreetingTemplate = $Index.templates.greeting.identity
$WordCountTemplate = $Index.templates.'word-count'.identity
$ShippingTemplate = $Index.templates.shipping.identity
Write-Host 'Workspace ready. Continue with Creating a capsule in this terminal.'
```

For your **first workspace**, run this in PowerShell, choosing your downloaded language:

```powershell
. "$HOME/Downloads/setup-lsf-workspace.ps1" -Language rust -Provision
```

The leading dot loads the `dev` shortcut and project settings into this terminal.
`-Provision` creates the shared LSF distro and leaves other distros alone. For later
workspaces, omit `-Provision` to reuse it.

## If you use Linux

Use Ubuntu 24.04 x86-64, Linux 6.8 or newer, and Python 3.13.5 at
`/usr/local/bin/python3.13`. Run as your ordinary account. Your host administrator
supplies this interpreter; the downloaded frontend contains the helper.

<!-- lsf-download: setup-lsf-workspace.sh -->

```bash
set -euo pipefail
umask 077
export Inputs="${LSF_INPUTS:-$HOME/LSF-inputs-alpha4}"
export Language="${1:-rust}"
export Workspace="${2:-test-my-greeting}"
Project="${3:-$HOME/Projects/My greeting}"
export Port="${4:-18080}"
case "$Language" in rust|c|typescript|go|java|dotnet) ;; *) echo 'Choose a supported language.' >&2; return 2;; esac
[[ "$Workspace" =~ ^test-[a-z0-9][a-z0-9-]*$ ]] || { echo 'Use a test- workspace name.' >&2; return 2; }
[[ "$Port" =~ ^[0-9]+$ ]] && ((Port >= 1024 && Port <= 65535)) || { echo 'Choose a port from 1024 to 65535.' >&2; return 2; }
Frontend="$Inputs/frontend/bin/latent-dev"
State="${LSF_STATE:-$HOME/.latent-dev-tutorial}"
Admission=signed-fixture
if [[ "$Language" == rust || "$Language" == c ]]; then Admission=trusted-local; fi
mkdir -p "$(dirname "$Project")"
python3 - <<'PY'
import hashlib, json, os, pathlib, shutil
root = pathlib.Path(os.environ['Inputs'])
language = os.environ['Language']
workspace = os.environ['Workspace']
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
save(workspace+'-runtime.json', dict(common, schemaVersion='latent.dev.install-inputs.v1',
     releaseDirectory=str(root/'native'), publisherPolicy=str(root/'native-policy.json'),
     profile='local-experimental-v1', port=int(os.environ['Port'])))
save(workspace+'-tools.json', dict(common, schemaVersion='latent.dev.tool-inputs.v1',
     bundleDirectory=str(root/language), publisherPolicy=str(root/'developer-policy.json'), language=language))
PY
dev() { "$Frontend" --state-root "$State" dev "$@"; }
dev doctor
dev connect --workspace "$Workspace" --backend-config "$Inputs/direct-backend.json"
dev install --workspace "$Workspace" --runtime-inputs "$Inputs/$Workspace-runtime.json"
dev install-tools --workspace "$Workspace" --tool-inputs "$Inputs/$Workspace-tools.json"

Version=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["version"])' "$Inputs/developer-policy.json")
VerifierIdentity="sha256:$(sha256sum "$Inputs/gh-linux" | cut -d' ' -f1)"
dev acquire --bundle-directory "$Inputs/$Language" \
    --publisher-policy "$Inputs/developer-policy.json" --trusted-root "$Inputs/trusted_root.jsonl" \
    --verifier "$Inputs/gh-linux" --verifier-sha256 "$VerifierIdentity" \
    --version "$Version" --target linux-x86_64 --allow-candidate > "$Inputs/$Workspace-templates.json"
Bundle=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["result"]["bundle"])' "$Inputs/$Workspace-templates.json")
GreetingTemplate=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["templates"]["greeting"]["identity"])' "$State/bundles/$Bundle/templates.json")
WordCountTemplate=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["templates"]["word-count"]["identity"])' "$State/bundles/$Bundle/templates.json")
ShippingTemplate=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["templates"]["shipping"]["identity"])' "$State/bundles/$Bundle/templates.json")
echo 'Workspace ready. Continue with Creating a capsule in this terminal.'
```

Run this in Bash, choosing your downloaded language:

```bash
source "$HOME/Downloads/setup-lsf-workspace.sh" rust
```

`source` loads the `dev` shortcut and project settings into this terminal.
Two workspaces under the same Linux account do not protect data from that
account; use separate accounts when that matters.

## Continue with your application

Expect successful installation results followed by **Workspace ready**. The node
has not started yet. Open [Creating a capsule](../component-development/creating-a-capsule.md)
to create the project, build it, start the node and send your first request.
The remaining development commands are shared across Windows and Linux.

Rust and C use the explicit `trusted-local` profile for your disposable development
code. The other languages use `signed-fixture` with their compiler's required
runtime permissions. This fixture approves one build for 30 minutes; a changed
build or expired fixture needs a fresh disposable workspace. The [edit guide](../learn/deliver-and-recover-a-capsule.md)
explains this and the supported automatic watch loop.

## Set up another project

Reuse the same downloads. Choose a different workspace and project; use a different
port if both nodes will run together. For a word counter, **on Windows**:

```powershell
. "$HOME/Downloads/setup-lsf-workspace.ps1" -Language rust -Workspace test-my-words -Project "$HOME/Projects/My words" -Port 18081
```

Or **on Linux**, the arguments are language, workspace, project and port:

```bash
source "$HOME/Downloads/setup-lsf-workspace.sh" rust test-my-words "$HOME/Projects/My words" 18081
```

If you chose a custom download directory, supply `-Inputs PATH` on Windows or set
`LSF_INPUTS` before sourcing the Linux script. Custom private state uses `-State`
or `LSF_STATE`; keep it outside the project and let the frontend create it.

For an occupied port, choose another port for a new workspace. If setup fails,
inspect the reported error before running more commands. A partial WSL import
needs `dev wsl-status` and the documented recovery path; do not repeat an uncertain
operation. See [Developer commands](../how-to/developer-commands.md).

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
