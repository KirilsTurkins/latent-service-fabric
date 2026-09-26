# Build a packaged capsule in your language

Create a greeting, word counter or shipping calculator in Rust, C, TypeScript,
Go, Java or C#. The same development commands build each project and check its
actual typed results on a Linux node. The compiler and runtime profile come from
the selected language bundle; your Windows machine needs no language compiler.

For an editable Rust greeting with automatic watch, use the
[Windows application walkthrough](windows-application.md). This page supplies
the common signed-test route for all six languages. A signed fixture approves
one built component for a disposable development workspace; it is not a
production package-signing service.

## 1. Select the tools and workspace

[Get the developer tools](../start/developer-setup.md) with your chosen language.
In Windows application steps [1](windows-application.md#1-obtain-the-selected-inputs)
and [2](windows-application.md#2-authenticate-and-provision-the-workspace), use
the same `$Language` and input directory. Those two steps create your protected
workspace and install the matching node and compiler. Keep that terminal open.
Use a new workspace and project path when trying another language.

| `$Language` | Write your application in | Language-specific reference |
| --- | --- | --- |
| `rust` | Rust | [Rust authoring](rust-authoring.md) |
| `c` | C | [C authoring](c-authoring.md) |
| `typescript` | TypeScript | [TypeScript authoring](typescript-authoring.md) |
| `go` | Go | [Go authoring](go-authoring.md) |
| `java` | Java | [Java authoring](java-authoring.md) |
| `dotnet` | C# | [C# authoring](dotnet-authoring.md) |

The typed examples are available in all six languages on
[Creating a capsule](creating-a-capsule.md). Select the language tabs to compare
the implementations; they keep the same contract and expected result.

## 2. Create a project from the selected template

Choose `greeting`, `word-count` or `shipping`. Start with `greeting`:

```powershell
$Example = 'greeting'
$Templates = Invoke-LsfDev acquire --bundle-directory (Join-Path $Inputs $Language) `
    --publisher-policy $DeveloperPolicy --trusted-root $TrustedRoot `
    --verifier $WindowsVerifier --verifier-sha256 $WindowsVerifierSha256 `
    --version $Version --target linux-x86_64 --allow-candidate
$Index = Get-Content -LiteralPath (Join-Path $State "bundles\$($Templates.bundle)\templates.json") `
    -Raw -Encoding UTF8 | ConvertFrom-Json
$Template = $Index.templates.PSObject.Properties[$Example].Value
Invoke-LsfDev init $Project --bundle $Templates.bundle --template "$Language/$Example" `
    --template-sha256 $Template.identity
```

Open the project. `app` contains your editable source and WIT contract;
`tests/scenarios.json` lists success and declared-error cases with their input
and expected-result files. `latent.project.json` identifies the recipe and its
tools. Review those files before trusting the project.

## 3. Build and prepare the disposable test node

```powershell
Invoke-LsfDev trust --workspace $Workspace --project $Project
Invoke-LsfDev build --workspace $Workspace --project $Project
Invoke-LsfDev prepare-test --workspace $Workspace --consent-test-fixtures
```

Expect a successful build and a prepared signed fixture. Required runtime
capabilities are explicit: Java and Go require clocks, Go also needs entropy,
and C# requires its monotonic GC clock. The maintained test profile supplies
only the declared fixture grants. A denied or unsupported import remains an
error. General Node.js, JVM, CLR and operating-system access are not provided.

The fixture binds this build and expires after 30 minutes. If it expires or you
change the accepted build, create a fresh disposable test workspace and prepare
that new build. Do not replace the selected fixture policy to make a failed
test pass. The Rust provider-free watch path is separately explained in the
Windows walkthrough.

## 4. Run the node and tests

Open a second PowerShell terminal and start foreground `up` with the same state
directory and workspace. For the default paths from the Windows guide:

```powershell
& (Join-Path $env:USERPROFILE 'LSF-inputs-alpha4/frontend/bin/latent-dev.exe') `
    --state-root (Join-Path $env:LOCALAPPDATA 'LatentDev-tutorial') `
    dev up --workspace test-my-greeting
```

Use your chosen workspace name if you changed it. Wait for the `ready` event.
In the first terminal, deploy and run the scenarios:

```powershell
Invoke-LsfDev deploy --workspace $Workspace
$Tests = Invoke-LsfDev test --workspace $Workspace --environment node
$Tests.passed
$Tests.results | Select-Object id, status, category
```

Expect `True`, with successful typed results and the expected declared errors:

| Template | Example input | Expected result |
| --- | --- | --- |
| Greeting | `Ada` | `Hello, Ada!` |
| Word count | `LSF runs small programs` | `4` |
| Shipping | Two items, standard delivery | `650` cents |

An empty greeting name or invalid shipping quantity should produce the named
application error case, not a transport failure. Check `status` and `logs` for
a failed build, node readiness or fixture problem. A lost invocation response
requires `recover` on the original operation; do not repeat an uncertain call.

## 5. Retain or clean up

```powershell
Invoke-LsfDev down --workspace $Workspace
Invoke-LsfDev status --workspace $Workspace
```

Down stops the owned node and retains the project, deployment and data. Starting
`up` again should leave that deployment callable without another deployment.
When finished with this disposable workspace, remove it explicitly:

```powershell
Invoke-LsfDev purge --workspace $Workspace --confirm-workspace $Workspace
```

Your application source remains on Windows. Only remove the owned WSL distro
after all its workspaces have been purged, using the separate confirmation in
the Windows guide. [Portable tests](portable-tests.md) can run the already
compiled capsule on native Windows within their documented supported subset.
