# Develop an application with packaged tools

Use `latent-dev` to create an application outside the LSF repository, build its
WebAssembly component, and run it on an explicitly selected Linux development
node. The frontend contains its own interpreter. You do not need to compile LSF,
install a language SDK on Windows, or write node credentials.

These tools currently ship as **nonpublishing candidates**. Obtain an exact
candidate and independently approved publisher policies from your maintainer.
A successful CI build alone is not approval. There is no public installer or
`latest` download to substitute for that handoff. Public release availability
is described in [installation](../installation.md).

| Your environment | Follow this path | Where the component runs |
| --- | --- | --- |
| Windows x86-64 with WSL2 | [Create and edit a Windows application](../component-development/windows-application.md) | A private workspace in the explicitly provisioned Linux distro |
| Ubuntu 24.04 x86-64 | [Select direct Linux](../component-development/linux-workspace.md#direct-linux) | Your selected unprivileged Linux workspace |
| Windows or Linux with a provisioned SSH host | [Select an SSH workspace](../component-development/linux-workspace.md#an-explicit-ssh-host) | The explicitly named Linux host and account |
| Windows x86-64 with already compiled component files | [Run portable capsule tests](../component-development/portable-tests.md) | A native Windows test process, within its closed supported subset |
| An existing supported container toolchain | [Optional terminal devcontainer](../component-development/devcontainer.md) | The selected SSH node; the container is a development client |

The managed WSL image and direct/SSH hosts use Ubuntu 24.04 x86-64 with Linux
6.8 or newer, the selected helper, and its pinned Python 3.13.5 interpreter.
The qualified Windows runs used WSL 2.7.14 and kernel 6.18.33.2. The portable
host does not provide a production Windows node or establish Linux sandbox,
resource-pressure, or external-capsule isolation guarantees.

Mac, Lima, Apple Silicon, Windows ARM64 and Linux ARM64 are outside this support
statement. A backend or compiler not listed in the selected bundle fails
explicitly; it is never silently replaced by portable execution.

## Choose a language

All six selections use `dev init`, `dev build`, and the same versioned project
and test contracts. The delivered compilers run on Linux x86-64, including the
managed WSL backend. Native Windows **execution of portable tests** does not
imply native Windows **compilation** support.

| Selection | Language-owned recipe | Application files | Development admission |
| --- | --- | --- | --- |
| `rust` | [Rust](../component-development/rust-authoring.md) | `app/src`, `app/wit` | Provider-free greeting supports explicit trusted-local watch |
| `c` | [C](../component-development/c-authoring.md) | C source and WIT under `app` | Provider-free greeting supports trusted-local; signed tests are available |
| `typescript` | [TypeScript](../component-development/typescript-authoring.md) | TypeScript source and WIT under `app` | Use the selected bounded engine profile |
| `go` | [Go](../component-development/go-authoring.md) | Go source and WIT under `app` | Signed test fixture and required runtime capability bindings |
| `java` | [Java](../component-development/java-authoring.md) | Java source and WIT under `app` | Signed test fixture and bounded Java engine profile |
| `dotnet` | [C#](../component-development/dotnet-authoring.md) | C# source and WIT under `app` | Signed test fixture and bounded NativeAOT profile |

The language pages explain the maintained recipes and source-level contracts;
their contributor bootstrap commands are not prerequisites for the packaged
workflow. Start with the Windows guide's Rust greeting to exercise edit/watch.
Select another language's authenticated tool bundle to build and test its
greeting. A signed test fixture binds one accepted build and expires after
30 minutes: use a new disposable test workspace for changed builds or expired
fixtures. This is an explicit test policy, not a production signing service.

## Keep the two trust decisions separate

Publisher verification authenticates the selected frontend, helper, runtime,
template and compiler bytes. Workspace trust authorizes your reviewed project
recipe to use those tools. Opening a folder does neither. VS Code is optional;
its generated process tasks run the same frontend commands as a terminal.

Choose `local-experimental-v1` only for controlled development. An
`external-capsule-v1` request must satisfy that profile's actual platform and
admission requirements. A denied capability, unsupported profile or failed
signature check is not a reason to weaken the selected policy.

Ordinary `down` retains your deployment and data. Destructive purge is a
separate command naming the exact owned workspace or distro. After a lost
response, inspect `status` and recover the original operation; do not repeat an
invocation whose result is unknown.
