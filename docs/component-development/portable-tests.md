# Run portable capsule tests on Windows

The native Windows test host executes already compiled WebAssembly components
without WSL, a Linux node or a VM. It is a controlled development test process,
with a closed set of imports and execution controls. It is not a Windows
production node and does not certify Linux isolation, admission or performance.

[Get the developer tools](../start/developer-setup.md#windows-download-and-verify).
The authenticated Windows developer bundle contains
`latent-portable-test-host.exe`, plus your application project and its compiled
component, capsule manifest and contracts. Use the exact three files produced
by that application's build, preserving the paths listed under `artifacts` in
`latent.project.json`. A build may run on a separately selected Linux/WSL/CI host;
the portable invocation itself does not contact that host or start a VM.

The compiler's package assembly and admission evidence are separate from these
test inputs. A successful portable test does not authorize publishing or
deploying a package. Source inspection, a checksum and execution authority are
different observations.

## Select the native host and application

Use the authenticated frontend and independent verification inputs from
[Windows step 1](windows-application.md#1-obtain-the-selected-inputs). Acquire the
Windows bundle into the private host cache, then explicitly request portable
execution. `$Artifacts` is the root under which the descriptor's artifact paths
exist; it is not a node state directory.

```powershell
$PortableBundle = Invoke-LsfDev acquire --bundle-directory (Join-Path $Inputs 'windows') `
    --publisher-policy $DeveloperPolicy --trusted-root $TrustedRoot `
    --verifier $WindowsVerifier --verifier-sha256 $WindowsVerifierSha256 `
    --version $Version --target windows-x86_64 --allow-candidate
$Artifacts = 'C:\My application build'
$Tests = Invoke-LsfDev test --workspace test-native-greeting --environment portable `
    --project $Project --artifacts $Artifacts --portable-bundle $PortableBundle.bundle `
    --controlled-development
$Tests.passed
$Tests.results | Select-Object id, status, category
```

This workspace is a private **test-report** location, not a Linux node
connection. Portable test processes are bounded and reaped when the command
finishes; there is no foreground `up` process to keep running. The report
identifies `portable`, the native host and selected profile. Unsupported required
scenarios make coverage fail; they do not count as successful skipped tests.

For a greeting, success and the declared empty-name error should agree with the
same component on the Linux node. Select a focused case with `--select CASE_ID`.
The selected language's bounded engine profile still applies on Windows.

## Read support and differences

| Scenario | Portable scope |
| --- | --- |
| Typed success, declared error and trap | Actual component execution with fresh activation state |
| Fuel, memory and deadline failures | Bounded native test execution; no production performance claim |
| Cancellation before execution | Supported closed prestart control |
| Cancel an observed running node activation | Requires the real node's Invoke/Cancel receipt workflow |
| Clock, random, logging and context | Only the declared native imports and explicit test provider configuration |
| Metrics and buffered HTTP | Explicit bounded providers/controlled peer; record the fixture substitution |
| Node-local services, immutable blobs, secrets and immediate events | Use their real Linux-node fixtures |
| Linux PSI, cgroups, sandbox and external-capsule admission | Not established by the portable host |

A capability denied by the native host may have a different platform error code
from the public Linux node's outer CLI. Shared comparisons retain both actual
codes and allow only the documented distinction; unrelated errors do not pass.
No requested node test silently runs here, and no unsupported portable import
silently gains a production provider.

Return to the [application development choices](../start/application-development.md)
or the [Windows edit/watch walkthrough](windows-application.md) when a test needs
the actual node lifecycle or recovery protocol.
