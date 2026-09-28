# Get the developer tools

Download the `0.1.0-alpha.5` toolkit once, then create applications without an
LSF source checkout or a host language compiler. Choose Rust, C, TypeScript,
Go, Java or C#. The toolkit contains the frontend, selected compiler and templates,
and a development-test node. Windows also uses a managed WSL2 image.

These are the exact packages used in the completed Windows/WSL, native Windows,
Linux and SSH qualification. Their original development-test signatures remain
intact. The release signs the selection that identifies those packages. Use
[native installation](../installation.md) for a persistent server; the toolkit's
test node enables explicit disposable test fixtures.

You need an independently installed **GitHub CLI 2.96.0 or newer** and network
access for the download. Windows needs PowerShell, its `tar` command, x86-64
hardware and working WSL2. Linux needs the supported Ubuntu 24.04 x86-64 host,
Python 3.12 or newer and the helper prerequisites described in the
[workspace setup](development-workspace.md#if-you-use-linux).
If GitHub CLI asks you to sign in, finish its normal sign-in flow first.

The commands authenticate the release selection before trusting its package
names, then check each original signature and file digest. They do not start a
node, install a system service, import a WSL distro or generate credentials.
Keep the resulting directory for offline setup and future projects.

## Download your toolkit

Save the setup file for your OS to **Downloads**, then run the short command
below it. Choose `rust`, `c`, `typescript`, `go`, `java` or `dotnet` (C#). You can expand **View the setup
script** to read exactly what it does; you do not need to copy or edit the script.
It keeps the publisher and package checks in place and stops if any check fails.

The download can be several hundred megabytes. The default destination is
`LSF-inputs-alpha5` in your home folder and must not already exist. If Downloads
is elsewhere on your machine, substitute that folder in the command.

### If you use Windows

<!-- lsf-download: get-lsf-tools.ps1 -->

```powershell
param(
    [ValidateSet('rust','c','typescript','go','java','dotnet')][string]$Language = 'rust',
    [string]$Inputs = (Join-Path $env:USERPROFILE 'LSF-inputs-alpha5')
)
$ErrorActionPreference = 'Stop'
$Version = '0.1.0-alpha.5'
$Repo = 'KirilsTurkins/latent-service-fabric'
if (Test-Path -LiteralPath $Inputs) { throw 'Choose a new input directory.' }
if ($Language -notin @('rust','c','typescript','go','java','dotnet')) { throw 'Choose a supported language.' }
New-Item -ItemType Directory -Path $Inputs | Out-Null
$Utf8 = [Text.UTF8Encoding]::new($false)
function Invoke-Gh {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$GhArguments)
    & gh @GhArguments
    if ($LASTEXITCODE -ne 0) { throw 'GitHub download or verification failed; stop here.' }
}
$Source = (Invoke-Gh api "repos/$Repo/commits/$Version" --jq .sha).Trim()
Invoke-Gh release download $Version --repo $Repo --dir $Inputs `
    --pattern developer-selection.json --pattern SHA256SUMS.sigstore.json
$Roots = @(Invoke-Gh attestation trusted-root)
[IO.File]::WriteAllLines((Join-Path $Inputs 'trusted_root.jsonl'), $Roots, $Utf8)
Invoke-Gh attestation verify (Join-Path $Inputs 'developer-selection.json') `
    --bundle (Join-Path $Inputs 'SHA256SUMS.sigstore.json') `
    --custom-trusted-root (Join-Path $Inputs 'trusted_root.jsonl') --repo $Repo `
    --cert-identity "https://github.com/$Repo/.github/workflows/native-runtime-release.yml@refs/tags/$Version" `
    --source-ref "refs/tags/$Version" --source-digest $Source --signer-digest $Source `
    --deny-self-hosted-runners
$Selection = Get-Content -LiteralPath (Join-Path $Inputs 'developer-selection.json') -Raw | ConvertFrom-Json
if ($Selection.version -ne $Version -or $Selection.purpose -ne 'controlled-development-toolkit') { throw 'Wrong toolkit selection.' }
foreach ($Name in @('windows','wsl','native',$Language)) {
    $Bundle = $Selection.bundles.PSObject.Properties[$Name].Value
    $Directory = Join-Path $Inputs $Name
    New-Item -ItemType Directory -Path $Directory | Out-Null
    foreach ($File in $Bundle.files) {
        Invoke-Gh release download $Version --repo $Repo --dir $Directory --pattern $File.asset
        $Downloaded = Join-Path $Directory $File.asset
        if ((Get-FileHash -LiteralPath $Downloaded -Algorithm SHA256).Hash.ToLowerInvariant() -ne $File.sha256) { throw 'Package digest mismatch.' }
        Move-Item -LiteralPath $Downloaded -Destination (Join-Path $Directory $File.name)
    }
    $Policy = $Selection.policies.PSObject.Properties[$Bundle.policy].Value
    $Attestation = if ($Name -eq 'native') { 'SHA256SUMS.sigstore.json' } else { 'attestation.json' }
    Invoke-Gh attestation verify (Join-Path $Directory 'SHA256SUMS') `
        --bundle (Join-Path $Directory $Attestation) --custom-trusted-root (Join-Path $Inputs 'trusted_root.jsonl') `
        --repo $Repo --cert-identity "https://github.com/$Repo/$($Policy.workflow)@$($Policy.sourceRef)" `
        --source-ref $Policy.sourceRef --source-digest $Policy.sourceCommit --signer-digest $Policy.sourceCommit `
        --deny-self-hosted-runners
}
foreach ($Pair in @(@('developer','developer-policy.json'),@('runtime','native-policy.json'))) {
    $Policy = $Selection.policies.PSObject.Properties[$Pair[0]].Value
    [IO.File]::WriteAllText((Join-Path $Inputs $Pair[1]), ($Policy | ConvertTo-Json), $Utf8)
}
$Verifier = $Selection.linuxVerifier
$VerifierArchive = Join-Path $Inputs 'gh-linux.tar.gz'
Invoke-WebRequest -Uri $Verifier.url -OutFile $VerifierArchive
if ((Get-FileHash -LiteralPath $VerifierArchive -Algorithm SHA256).Hash.ToLowerInvariant() -ne $Verifier.sha256) { throw 'Linux verifier digest mismatch.' }
tar -xzf $VerifierArchive -C $Inputs $Verifier.member
if ($LASTEXITCODE -ne 0) { throw 'Linux verifier extraction failed.' }
Copy-Item -LiteralPath (Join-Path $Inputs $Verifier.member) -Destination (Join-Path $Inputs 'gh-linux')
Expand-Archive -LiteralPath (Join-Path $Inputs 'windows/latent-dev-windows-x86_64.zip') `
    -DestinationPath (Join-Path $Inputs 'frontend')
$Frontend = Join-Path $Inputs 'frontend/bin/latent-dev.exe'
& $Frontend dev doctor
if ($LASTEXITCODE -ne 0) { throw 'Satisfy the reported host prerequisites before continuing.' }
```

Open PowerShell and run:

```powershell
& "$HOME/Downloads/get-lsf-tools.ps1" -Language rust
```

### If you use Linux

<!-- lsf-download: get-lsf-tools.sh -->

```bash
set -euo pipefail
umask 077
export LSF_LANGUAGE="${1:-rust}"
export LSF_INPUTS="${2:-$HOME/LSF-inputs-alpha5}"
case "$LSF_LANGUAGE" in rust|c|typescript|go|java|dotnet) ;; *) echo 'Choose a supported language.' >&2; exit 2;; esac
mkdir "$LSF_INPUTS"
cd "$LSF_INPUTS"
python3 - <<'PY'
import hashlib, json, os, pathlib, subprocess, zipfile

root = pathlib.Path.cwd()
repository = 'KirilsTurkins/latent-service-fabric'
version, language = '0.1.0-alpha.5', os.environ['LSF_LANGUAGE']
assert language in ('rust', 'c', 'typescript', 'go', 'java', 'dotnet')
def gh(*args):
    return subprocess.check_output(['gh', *args], timeout=900).decode('utf-8')
source = gh('api', f'repos/{repository}/commits/{version}', '--jq', '.sha').strip()
gh('release', 'download', version, '--repo', repository, '--dir', str(root),
   '--pattern', 'developer-selection.json', '--pattern', 'SHA256SUMS.sigstore.json')
roots = root/'trusted_root.jsonl'
roots.write_text(gh('attestation', 'trusted-root'))
def verify(file, attestation, workflow, ref, commit):
    gh('attestation', 'verify', str(file), '--bundle', str(attestation),
       '--custom-trusted-root', str(roots), '--repo', repository,
       '--cert-identity', f'https://github.com/{repository}/{workflow}@{ref}',
       '--source-ref', ref, '--source-digest', commit, '--signer-digest', commit,
       '--deny-self-hosted-runners')
verify(root/'developer-selection.json', root/'SHA256SUMS.sigstore.json',
       '.github/workflows/native-runtime-release.yml', f'refs/tags/{version}', source)
selection = json.loads((root/'developer-selection.json').read_text())
assert selection['version'] == version and selection['purpose'] == 'controlled-development-toolkit'
for name in ('linux', 'native', language):
    directory = root/name
    directory.mkdir()
    bundle = selection['bundles'][name]
    for file in bundle['files']:
        gh('release', 'download', version, '--repo', repository, '--dir', str(directory), '--pattern', file['asset'])
        downloaded = directory/file['asset']
        with downloaded.open('rb') as stream:
            assert hashlib.file_digest(stream, 'sha256').hexdigest() == file['sha256'], 'Package digest mismatch'
        downloaded.rename(directory/file['name'])
    policy = selection['policies'][bundle['policy']]
    attestation = 'SHA256SUMS.sigstore.json' if name == 'native' else 'attestation.json'
    verify(directory/'SHA256SUMS', directory/attestation, policy['workflow'], policy['sourceRef'], policy['sourceCommit'])
for kind, name in [('developer', 'developer-policy.json'), ('runtime', 'native-policy.json')]:
    (root/name).write_text(json.dumps(selection['policies'][kind])+'\n')
frontend = root/'frontend'
manifest = json.loads((root/'linux/developer-bundle.json').read_text())
with zipfile.ZipFile(root/'linux'/manifest['archive']['name']) as archive:
    archive.extractall(frontend)
for file in manifest['files']:
    path = frontend/file['path']
    path.chmod(0o700 if file['executable'] else 0o600)
print('Verified toolkit:', root)
print('Frontend:', frontend/'bin/latent-dev')
PY
"$PWD/frontend/bin/latent-dev" dev doctor
```

Open Bash and run:

```bash
bash "$HOME/Downloads/get-lsf-tools.sh" rust
```

## Check the result

Expect successful verification followed by the frontend's prerequisite report.
No node is running yet. Continue with [workspace setup](development-workspace.md).
Keep the downloaded packages so another workspace can use them offline.

If a download fails, keep its directory for diagnosis and choose a new input
directory for another attempt. Windows accepts `-Inputs PATH` after the language;
Linux accepts the directory as its second argument. If PowerShell blocks a
downloaded script, review it first, then use `Unblock-File` on that one file and
run it again; there is no need to change your machine's execution policy.

## Keep or remove the inputs

The input directory contains tools, templates and public verification material,
not project secrets or running-node state. Keep it to install another workspace
without downloading again. Delete only that directory when you no longer need
the offline packages. Node shutdown, workspace purge and WSL removal have
separate commands in the developer command guide; deleting downloads does none of them.
