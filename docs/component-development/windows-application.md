# Create and edit a Windows application

This PowerShell walkthrough uses an authenticated `latent-dev.exe`, a managed
WSL2 workspace, and the maintained Rust greeting template. Your source stays on
Windows. Its compiler, node credentials and runtime state stay in private Linux
storage. The example deliberately selects the provider-free trusted-local
development profile so that source edits can be deployed without a signing
service. Use it only for your own controlled application code.

The default language below is Rust. For C, TypeScript, Go, Java or C#, use
your selected language during setup, complete the common workspace steps 1–2,
then follow [Build a packaged capsule in your language](packaged-languages.md).
That path uses the matching signed test profile instead of the Rust watch example.

## 1. Obtain the selected inputs

Complete [Get the developer tools](../start/developer-setup.md#windows-download-and-verify)
with the `rust` language selection for this example, or your chosen language
for the six-language walkthrough. It produces an independently verified Windows
frontend and an offline input directory containing the matching WSL image,
native Linux runtime distribution, selected compiler/template bundle, independently
approved developer/runtime publisher policies, trusted roots, and pinned Windows
and Linux GitHub CLI verifiers. The verifiers must support attestation verification
with the selected offline trusted root. Use GitHub CLI 2.96.0 or newer.

The frontend must be verified **before its first execution**. The download
walkthrough verifies the attestation on `SHA256SUMS` against the approved repository,
workflow, branch and full source commit, verifies each named file's hash and size,
then extracts the selected Windows archive into a new directory. Do not use a
policy found inside an untrusted archive as independent approval. Online download
and offline verification are separate steps; all inputs below can be provisioned
before disconnecting the machine.

Use the input directory created by that walkthrough. The commands below
calculate verifier identities from the independently installed Windows CLI and
the already verified Linux CLI. Keep this PowerShell terminal open throughout
the walkthrough; later steps reuse its paths and helper.

```powershell
$Inputs = Join-Path $env:USERPROFILE 'LSF-inputs-alpha4'
$Language = 'rust'
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

function Invoke-LsfDev {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$DevArguments)
    $Lines = @(& $Frontend --state-root $State dev @DevArguments)
    if ($LASTEXITCODE -ne 0) { throw ($Lines -join "`n") }
    $Reply = $Lines[-1] | ConvertFrom-Json
    if ($Reply.code -ne 'success') { throw ($Lines -join "`n") }
    $Reply.result
}

Invoke-LsfDev doctor
```

Doctor reports host prerequisites; it does not claim an authenticated node is
running. WSL2 and hardware virtualization must already be available. If the kernel
is too old, arrange an explicit OS update before continuing. The frontend does
not upgrade shared WSL, alter the default distro, or install Docker.

Choose a new project path with an existing parent directory. Keep `$State` on a
local filesystem supporting private permissions, outside the source project.
The frontend creates its private state directory itself. Do not precreate it
with broad inherited access or place node state on a shared source mount.

## 2. Authenticate and provision the workspace

The input directory uses `wsl`, `native` and the selected language subdirectories for the
corresponding selected distributions. Verification is offline and checks the
independently pinned verifier before using it.

```powershell
$WslBundle = Invoke-LsfDev acquire --bundle-directory (Join-Path $Inputs 'wsl') `
    --publisher-policy $DeveloperPolicy --trusted-root $TrustedRoot `
    --verifier $WindowsVerifier --verifier-sha256 $WindowsVerifierSha256 `
    --version $Version --target linux-x86_64-wsl-rootfs --allow-candidate
$WslInventory = Get-Content -LiteralPath (Join-Path $State "bundles\$($WslBundle.bundle)\rootfs-inventory.json") `
    -Encoding UTF8 | ConvertFrom-Json
$Distro = Invoke-LsfDev provision --bundle $WslBundle.bundle --consent-provision
Invoke-LsfDev wsl-workspace --workspace $Workspace --helper-sha256 $WslInventory.helperSha256
```

Provisioning explicitly imports one owned distro. Creating a workspace gives it
a separate unprivileged Linux account. Another capsule in this application does
not require another VM. Save the returned distribution name for any later purge.

Create the two installation selections below outside your source project. They
contain public paths and verification policy, not node passwords. The installer
generates and protects the workspace's credentials.

```powershell
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
Invoke-LsfDev install --workspace $Workspace --runtime-inputs $RuntimeInputs
Invoke-LsfDev install-tools --workspace $Workspace --tool-inputs $ToolInputs
```

Use a different explicitly selected port for each simultaneously running
workspace. A port conflict is a failure; the controller does not kill its owner.

## 3. Create, review and build the greeting

Authenticate the template bundle on Windows as well as installing its compiler
in Linux. The authenticated template index supplies the exact greeting identity.

```powershell
$Templates = Invoke-LsfDev acquire --bundle-directory (Join-Path $Inputs 'rust') `
    --publisher-policy $DeveloperPolicy --trusted-root $TrustedRoot `
    --verifier $WindowsVerifier --verifier-sha256 $WindowsVerifierSha256 `
    --version $Version --target linux-x86_64 --allow-candidate
$TemplateIndex = Get-Content -LiteralPath (Join-Path $State "bundles\$($Templates.bundle)\templates.json") `
    -Encoding UTF8 | ConvertFrom-Json
$Greeting = $TemplateIndex.templates.greeting
Invoke-LsfDev init $Project --bundle $Templates.bundle --template rust/greeting `
    --template-sha256 $Greeting.identity
```

Open `app/src/lib.rs` and `app/wit/world.wit`. The exported function is
`greet(name: string) -> result<string, string>`: `Ada` produces `Hello, Ada!`,
while an empty name produces a declared application error. `tests/scenarios.json`
lists the real-node cases and their exact input/expected files. The language-owned
project also contains its native business-logic tests.

If this machine also has the template's pinned Rust 1.97.1 native toolchain and
its platform linker, run the business-logic unit test before building the
component:

```powershell
cargo +1.97.1 test --locked --manifest-path (Join-Path $Project 'app\Cargo.toml')
if ($LASTEXITCODE -ne 0) { throw 'Native business-logic test failed' }
```

Expect `greets_trimmed_names_and_explains_invalid_input` to pass. This optional
command tests ordinary application code on the host; it does not compile LSF
or exercise component bindings or node behavior. The packaged Windows workflow
does not install that native Rust/linker environment. If it is unavailable,
record this test as not run and continue with the installed Linux compiler and
real-node scenarios below. Do not label those results native unit-test coverage.

Review `latent.project.json`, especially its input roots, exclusions, pinned tools
and build arguments. Then explicitly trust that recipe and build it:

```powershell
Invoke-LsfDev trust --workspace $Workspace --project $Project
Invoke-LsfDev build --workspace $Workspace --project $Project
Invoke-LsfDev prepare-test --workspace $Workspace --consent-test-fixtures --admission trusted-local
```

The build uses the installed Linux compiler selection. No Windows Rust SDK or LSF
checkout is needed. Changing the recipe or tool selection invalidates trust.
Source synchronization preserves bytes and excludes `.git`, `.env`, SSH/cloud
credential directories and generated output. Add explicit exclusions for any
other confidential source files before building.

## 4. Run and test on the actual node

Open a **second PowerShell terminal** and run the following foreground command,
using the same paths and workspace selected above:

```powershell
& (Join-Path $env:USERPROFILE 'LSF-inputs-alpha4/frontend/bin/latent-dev.exe') --state-root (Join-Path $env:LOCALAPPDATA 'LatentDev-tutorial') `
    dev up --workspace test-my-greeting
```

Wait for the structured `ready` event with authenticated readiness. Leave that
terminal open. In the first terminal:

```powershell
Invoke-LsfDev doctor --workspace $Workspace
Invoke-LsfDev deploy --workspace $Workspace
$Tests = Invoke-LsfDev test --workspace $Workspace --environment node
$Tests.passed
$Tests.results | Select-Object id, status, category
```

Expect all three greeting cases to pass, including `declared-error`. A declared
error is an expected typed result in that case, not a transport failure. The
report's environment is `node`; a portable result cannot replace it.

Make a direct call and decode its typed response:

```powershell
$Reply = Invoke-LsfDev invoke --workspace $Workspace --service examples/my-greeting `
    --contract 'examples:greeting/api@1.0.0' --function greet `
    --input (Join-Path $Project 'tests\0-input.json')
[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($Reply.data.payload.data))
Invoke-LsfDev logs --workspace $Workspace
```

The answer is `[{"ok":"Hello, Ada!"}]`. The invocation records its activation
and selected revision; logs and status identify the same workspace and node.
There is no credential-copying step.

## 5. Edit, watch, and retain the last working revision

First run `Invoke-LsfDev down --workspace $Workspace`. The foreground up command
then exits. In that second terminal, start watch with the same explicit frontend
and state root:

```powershell
& (Join-Path $env:USERPROFILE 'LSF-inputs-alpha4/frontend/bin/latent-dev.exe') --state-root (Join-Path $env:LOCALAPPDATA 'LatentDev-tutorial') `
    --editor-diagnostics dev up --workspace test-my-greeting --project "$env:USERPROFILE\Projects\My greeting" `
    --watch --test-select greeting-0
```

Wait for `deployed` and the focused test result. In your editor, change `Hello,`
to `Welcome,` in `app/src/lib.rs`, including its native test expectation. Update
`tests/0-expected.json` and `tests/1-expected.json` to the corresponding new
answers, preserving their JSON byte format. Save the files. Watch builds a new
revision and reports its confirmed deployment and focused test result. Repeat
the direct call from step 4: it now returns `Welcome, Ada!`.

Remove a semicolon or add an invalid Rust statement, then save. Expect a compiler
location and `edit-failed`; the confirmed deployment remains callable. Repeat
the direct call: it still returns the last working greeting. Restore valid
source. A successful rebuild clears the old editor diagnostic. Failed focused
tests are visible and do not automatically roll back a deployed revision.

To use VS Code's task picker, generate its configuration explicitly:

```powershell
Invoke-LsfDev editor --workspace $Workspace --project $Project --frontend $Frontend
```

Open the project and choose **Tasks: Run Task**. The generated **LSF: build**,
**watch**, **logs**, **status**, **recover original operation** and **down** tasks
use the same commands. Existing `tasks.json` files are preserved. Opening a
downloaded folder starts no task, installs no tool and does not trust its recipe.
Use **LSF: down** for shutdown; terminating a terminal may leave the remote node
running, so inspect status before claiming cleanup.

## 6. Recover, restart, and stop

After a lost response, inspect the workspace before issuing new work:

```powershell
Invoke-LsfDev status --workspace $Workspace
Invoke-LsfDev recover --workspace $Workspace
```

Recovery queries the original operation ID. `no-pending-operation` means there
is nothing to reconcile. An unknown or expired receipt remains uncertain; keep
the original intent and do not repeat deploy or Invoke. A newer deployment from
another actor is not overwritten. After sleep/resume or WSL interruption, run
status first, then recover if needed. An unreachable backend is not confirmed
shutdown.

Run `Invoke-LsfDev down --workspace $Workspace`, then start ordinary `dev up`
again in the second terminal. The direct call must return the retained greeting
without running deploy again. Finish with down and confirm status is stopped.

Ordinary down retains data. Only when you deliberately want to remove this
workspace, use its exact name:

```powershell
Invoke-LsfDev purge --workspace $Workspace --confirm-workspace $Workspace
Invoke-LsfDev wsl-status
```

Your authored Windows project remains. Distro removal is another explicit step,
allowed only after all its owned workspaces have been purged:
`Invoke-LsfDev wsl-purge --confirm-distribution $Distro.distribution`.
Never substitute another registered distro's name or run a global WSL shutdown
as application cleanup.

## If a step fails

| Symptom | Next action |
| --- | --- |
| Missing virtualization, old kernel, PSI or sandbox control | Satisfy the selected profile's actual OS prerequisites, or choose an explicitly provisioned supported SSH backend |
| Signature, version, ABI, helper or target mismatch | Obtain a matching approved input set; do not execute a rejected artifact |
| Shared-filesystem or protected-path rejection | Put state in private local storage and remove links, case aliases or unsupported mounts from selected inputs |
| Occupied port | Stop only your known owner, or create a new workspace with another selected port |
| Compiler failure or stale output | Fix the source/tool selection; the accepted deployment is retained |
| Active build or another controller owns the workspace | Inspect status/build-status and wait for that work to settle; do not replay an uncertain effect |
| Denied capability | Review the component's explicit scoped policy; do not switch profiles to make a denied test pass |
| Interrupted transfer/extraction | Inspect the original selection; only use its documented explicit resume option for unchanged inputs |
| Lost connection or cleanup not confirmed | Keep the original workspace and operation identity, restore connectivity, then inspect status/recover |

For another language, select its authenticated compiler/template bundle and use
the matching language identifier from the [support table](../start/application-development.md#choose-a-language).
Managed-language signed fixtures need a fresh test workspace after an accepted
build changes. [Portable tests](portable-tests.md) are a separate, explicit
execution choice for already compiled component files.
