# Changes since alpha.5

The published developer toolkit and native binaries are **0.1.0-alpha.5**.
The Development documentation also describes source changes merged after that
release. Select alpha.5 in the website version menu when following its downloaded
tools; a Development example can require commands or profiles those binaries do
not contain. Install releases through [developer setup](developer-setup.md) or
[native installation](../installation.md).

For the newer workflows below, use a source checkout and its pinned
[toolchain](../development/toolchain.md). Follow each language's authoring recipe
and its stated qualification boundary. These changes do not select a new runtime
automatically or upgrade an existing toolkit installation.

## Choose the next task

| Task | Development guide |
| --- | --- |
| Add an application library, capture a private dependency or build offline | [Add application libraries](../how-to/add-application-libraries.md), with separate recipes for all six languages |
| Use immutable application data | [Packaged resources](../component-development/packaged-resources.md); standard lookup support depends on the language profile |
| Generate source with an approved build tool | [Library workflow](../how-to/add-application-libraries.md#approve-executable-build-inputs), including Java annotation processors |
| Compile ordinary Java HTTP registration | [Java HttpServer](../component-development/java-httpserver.md) and [captured server declarations](../component-development/server-source.md) |
| Check an HTTP or typed-service composition before dispatch | [Inspect a composition](../how-to/inspect-a-composition.md), then inspect actual target preparation and authorized activation diagnostics |
| Stage state changes and deferred work together | [Transactional aggregate guest](../component-development/transactional-authoring.md) and [state/effect architecture](../architecture/state-and-effects.md) |
| Recover a command or inspect its deferred effect after response loss | [Transaction recovery](../operations/transaction-recovery.md) |
| Serve a custom static 404 or inspect capture headroom | [Static sites](../component-development/static-sites.md) and [static publication](../operations/static-release-workflow.md) |
| Select and reproduce a contributor check | [Local tests](../development/local-tests.md), [deterministic tests](../development/deterministic-tests.md) and [CI command ownership](../testing/ci-command-contracts.md) |

## Runtime and state boundaries

Ordinary library APIs still need compatible imports, finite resource owners and
an explicitly supported runtime profile. Capturing a package is not proof that
every API in it runs. Consult [library compatibility](../component-development/library-compatibility.md)
and the language guide before choosing threading, timers, sockets or HTTP.
The Rust standard runtime, TypeScript runtime, Java continuation profiles and
.NET clock/resource paths have different executed coverage and remaining work.

Transactional applications select `lsf-host-abi-phase4-v1` explicitly. They need
the configured protected store, signed transaction companion, namespace and
current operation/result/effect permissions. Installing compiler inputs does
not install these node owners. Existing stateless applications retain their
stateless profile; portable Windows testing does not provide transaction storage.

Do not point current source at an older state directory and assume it can be
upgraded. Follow the selected [storage profile](../architecture/state-and-effects.md#incoming-identity-formats-and-linked-retention)
and [coupled backup workflow](../operations/local-storage-recovery.md).
Supported upgrades preserve pending commands and effects; code rollback does
not roll back business state or external actions. Older-history restore has its
own incarnation and paused reconciliation requirements.

## Development acceptance

Merged source, an executed fixture and a packaged release establish different
boundaries. Phase 4's collective gate and the broader SDK library/runtime gates
remain open. PR #970 adds current installed recovery to this documentation
branch, but is still pending integration and complete terminal/pending native
qualification. Neither its historical receipts nor alpha.5 qualify that work.

Maintainers can use the [post-release documentation audit](../development/documentation-audit-2026-10-14.md)
for the exact release tree, merged PR inventory, corrected claims and retained
acceptance boundaries. [The roadmap](../roadmap.md) lists the remaining phases.
