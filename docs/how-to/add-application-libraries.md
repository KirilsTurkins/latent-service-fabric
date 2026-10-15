# Add application libraries

Use this workflow with the Development source tools and an existing capsule
project. It captures your application's dependencies separately from the SDK and
compiler. The alpha.5 downloads do not include all these newer authoring commands;
start with [Changes since alpha.5](../start/development-changes.md) and the pinned
[toolchain](../development/toolchain.md).

## Select the language recipe

| Language | Add, resolve, review, build and update | Executable source generation |
| --- | --- | --- |
| Rust | [Cargo library workflow](../component-development/rust-library-authoring.md) | [Captured Cargo build scripts and proc macros](../component-development/rust-dependencies.md) |
| C | [C source and static-library workflow](../component-development/c-dependencies.md) | [Approved C generators](../component-development/c-generators.md) |
| TypeScript | [npm library workflow](../component-development/typescript-library-authoring.md) | [Approved TypeScript generators](../component-development/typescript-generators.md) |
| Go | [Go module workflow](../component-development/go-library-authoring.md) | [Approved Go generators](../component-development/go-generators.md) |
| Java | [Maven and local JAR workflow](../component-development/java-dependencies.md) | [Approved Java generators and annotation processors](../component-development/java-generators.md) |
| C#/.NET | [NuGet and local package workflow](../component-development/dotnet-dependencies.md) | [Explicit executable-input approval](../component-development/dotnet-dependencies.md) |

Use the corresponding source-owned `tools/<language>_capsule.py` command, or the
recipe from the same authenticated SDK installation as your project. Keep that
SDK's lock and compiler selection unchanged when adding application libraries.
The language recipe controls native resolver semantics, target/features,
classpath or package ordering and eligible runtime APIs.

## Capture and review a change

1. Edit the application's native dependency declaration through its normal
   language workflow. A frontend project keeps editable sources in its selected
   `app/` directory and the captured dependency manifest/lock beside the outer
   `latent.project.json`. Do not add another project descriptor or capture lock
   inside `app/`.
2. Resolve explicitly to a **new candidate path**. Inspect the candidate and its
   receipt: direct/transitive inputs, native locks, selected profile/features,
   original and transformed bytes, licenses and executable inputs. Resolution
   preserves the currently accepted lock.
3. Accept only the exact reviewed candidate. Rust, C, TypeScript, Go and Java use
   their recipe's `review-lock` operation with the expected digest. The .NET
   recipe uses an explicit copy of the inspected candidate to the accepted lock
   path, as shown in its guide. Keep `latent.dependencies.json`,
   `latent.dependencies.lock.json`, native locks and `dependency-inputs/objects/`
   together. Private repositories and credentials belong in separate resolution
   configuration, never in a public lock or build receipt.
4. For a frontend project, run `latent-dev dev trust --workspace "$Workspace"
   --project "$Project"` after a dependency lock, runtime profile or executable
   input selection changes. The build verifies captured objects offline before
   compilation and rechecks them afterwards. Missing or changed bytes fail.
5. Run the language's maintained tests and watch path, then sign, admit and test
   the actual component on an authorized node. Preserve a failed build's receipt
   and the last working deployment. Use `dev status` and `dev recover` for an
   uncertain frontend operation before doing more work.

The [capture reference](../component-development/application-dependencies.md)
defines graph, archive and transport bounds. The frontend snapshot is smaller
than the standalone capture store: 2,048 files, 16 MiB per file and 64 MiB total.
A larger reviewed closure needs the standalone recipe; cached bytes do not
bypass these limits or grant runtime authority.

## Approve executable build inputs

Passive dependency capture does not execute package hooks, processors, build
scripts or generators. Use the language's separate request/approval stage, review
the exact tool and input digest, and select that digest explicitly. The Linux
namespace executor has no network, inherited credentials or writable original
inputs; an unsupported host fails closed.

Generated source enters the normal compiler path only after bounded output and
ownership checks. A changed tool, source, dependency selection or SDK invalidates
the previous approval. Captured generated output permits later offline builds;
it does not authorize another execution or qualify a library's runtime behavior.

## Check runtime compatibility and resources

Inspect [the final component compatibility report](../component-development/library-compatibility.md).
It records actual imports and rejected or unevaluated surfaces; a successful
capture is not a general library compatibility claim. Use
[composition inspection](inspect-a-composition.md) for current target preparation,
and execute your application against the selected node/profile.

For immutable data, use [packaged resources](../component-development/packaged-resources.md).
Resource capture grants no filesystem or scratch storage. Threading, timers,
outbound networking and deferred effects require their separately selected
language and node owners. Repeat the same capture, review and trust sequence
when updating or removing a dependency.
