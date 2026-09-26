# Application development

Write a small program, build it into a capsule, and call it on your development
node. The `latent-dev` toolkit creates the project and manages the compiler,
node and credentials. You do not need to build LSF or install a language compiler
on your desktop.

Follow this path once, choosing your language and OS inside the guides:

1. [Get the developer tools](developer-setup.md).
2. [Set up your development workspace](development-workspace.md).
3. [Create a capsule](../component-development/creating-a-capsule.md): greet someone,
   count words or calculate a shipping price.
4. [Edit, deploy and recover](../learn/deliver-and-recover-a-capsule.md): change a
   response, test it, keep the last working build and restart your node.

Keep [Developer commands](../how-to/developer-commands.md) nearby for daily work.
It explains `init`, `build`, `up`, `deploy`, `test`, `invoke`, `logs`, `recover`,
`down` and the other development commands. The separate [Operator CLI](../reference/operator-cli.md)
is for administering nodes and deployments directly.

## Choose a language

The capsule tutorial has one shared workflow and selectable code examples for
all six languages. Use the corresponding identifier during tool download and setup:

| Selection | Language | Compiler and runtime reference |
| --- | --- | --- |
| `rust` | Rust | [Rust profile](../component-development/rust-authoring.md) |
| `c` | C | [C profile](../component-development/c-authoring.md) |
| `typescript` | TypeScript | [TypeScript profile](../component-development/typescript-authoring.md) |
| `go` | Go | [Go profile](../component-development/go-authoring.md) |
| `java` | Java | [Java profile](../component-development/java-authoring.md) |
| `dotnet` | C# | [C# profile](../component-development/dotnet-authoring.md) |

The references explain compiler limits and lower-level integration. They are
not additional tutorials to complete before creating your application.

## Where your application runs

On Windows x86-64, the toolkit runs its compiler and node in WSL2. On Ubuntu
24.04 x86-64, it can run them directly. Either desktop can select an explicitly
provisioned SSH host instead. Each guide includes the relevant OS instructions;
the capsule you write is the same kind of program in each case.

[Portable tests](../component-development/portable-tests.md) run already compiled
components on Windows without starting a Linux node. They cover a smaller set
of behavior and do not replace real-node tests. An [optional devcontainer](../component-development/devcontainer.md)
provides a terminal client for a selected SSH node.

The supported Linux host needs kernel 6.8 or newer and the selected helper's
Python 3.13.5 interpreter. Mac, Lima, Apple Silicon and ARM64 are not supported by
this toolkit. For a persistent server, follow [native installation](../installation.md).

## Trust your project before building

Review `latent.project.json` before running `dev trust`. It names the source
inputs, compiler and build recipe that will execute. Download verification checks
the tool publisher; project trust approves the recipe you chose. Opening an editor
does neither automatically.

Start with the disposable development workspace. Production package signing,
admission policies and persistent server operations have their own references.
When a response is lost, inspect the original operation with `dev recover` before
doing more work: repeating an uncertain request can execute it twice.
