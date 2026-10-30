# Development documentation audit: 25 October 2026

This pass compares the previous delivered audit, PR #988 at
`6f637e989864766ab298f902ada3d331d9959d29`, with development source
`0ca8e0f574b3b8829c4691aa0d830e648f073a5e` (PR #1460). The baseline is an
ancestor of the inspected source. The comparison contains **455 first-parent
merged PRs**, **5,131 net changed paths** and **8,128 per-commit path touches**.
Ninety-five merges changed no Markdown or reStructuredText.

[The complete inventory](documentation-audit/2026-10-25.json) records every
merge SHA, PR, title, date, changed-path count, documentation paths and review
areas. Its area assignments connect changes to maintained contracts; they are
navigation classifications, not test results. File paths describe the original
merge, including paths later consolidated or removed. The review combined that
complete merge/path inventory with focused inspection of current implementation,
manifests, locks, command definitions and source-bound evidence in each area.

The latest published toolkit remains **0.1.0-alpha.5**. Current Development
source, selected experimental profiles and historical qualification products
must not be described as features of those downloaded binaries. Start with the
[changes guide](../start/development-changes.md) for the current task paths.

## Findings and maintained owners

| Area and representative merges | Finding and documentation disposition |
| --- | --- |
| Package architecture: #1128, #1134, #1438 | The package index reported 53 members, and an isolated-workspace paragraph still reported 52. The current root manifest has **55**: 43 crates, three applications, three SDK/compiler support packages and six tools. New READMEs explain the [native stream factory](../../crates/latent-stream-factory-native/README.md) and [Rust stdio bridge](../../sdk/rust-standard-stdio/README.md). The [package walkthrough](workspace-packages.md) and [index](../../crates/README.md) now agree with the manifest. |
| Component threading and compiler checkpoints: #1036, #1296, #1366 | The component-threading README still presented C as future work, and the engine introduction described cooperative execution as globally unavailable. [Component threading](../../crates/latent-component-threading/README.md) and [Wasmtime profiles](../runtime/wasmtime.md#selected-continuation-and-memory-profiles) now describe the exact C context-144 and Rust context-40 paths, host selection, source verification and default-off behavior. Closed-profile experiments do not qualify arbitrary pthread, std::thread, executor or CPU-loop fairness. |
| Selected native and value allocations: #1313, #1325, #1336, #1351, #1376, #1452 | Version-only engine descriptions missed the maintained Wasmtime source cohort and selected allocation hooks. [Engine architecture](../runtime/wasmtime.md), [resource budgets](../runtime/resource-budgets.md), capability/audit package READMEs and [VALIDATION](../../VALIDATION.md) now connect original precharge and physical retirement to the detailed codec, table, handle, buffer, Audit and registry controls. Selected backing may outlive a result waiter or Store; these controls are not a process-wide RSS guarantee. |
| Ordinary library runtime paths: #1180, #1249, #1399, #1400, #1406, #1455, #1457, #1460 | SDK introductions still applied older base-profile restrictions to newer explicit paths. The six guest/runtime introductions now distinguish closed/base behavior from selected HTTP, timer/task, standard-facility and module ports. The [v1 capability matrix](../component-development/runtime-capabilities.md) remains a source-bound snapshot, with navigation to later records instead of silently promoting its machine-readable rows. The duplicate Java transaction-template paragraph is removed. |
| Rust standard runtime and WASI HTTP: #1128, #1134, #1259, #1265, #1270, #1277 | The standard-runtime introduction still said there was no builder selection despite later owned sysroot, stdio and clock work. It now distinguishes those paths from the initial source PAL tests. [WASI HTTP architecture](../../sdk/wasi-http-runtime/README.md) explains the component producer, shared owners, separate consumer identities and copied interface inputs. The Rust guest feature/dependency reference includes the compiler-owned standard-logging bridge. |
| Dependency capture, private inputs, watch and compatibility: #1012, #1034, #1057, #1264, #1426, #1444 | The six language capture references already describe native declaration/lock, review, offline compilation and private credential boundaries. Current entry points now lead to those references and API-level diagnostics. Capture does not establish compatible initialization, runtime authority or successful execution. Historical capture and signed receipts retain their original source and toolchain identities. |
| Streams, kernel work and operator administration: #1007, #1050, #1144, #1368, #1378, #1384, #1385, #1390, #1392, #1429, #1430, #1438 | The standalone reference still called ADR-0061 pending review; the bounded design was accepted on 16 October. The reference now separates that decision from disabled production installation. Stream/native-factory READMEs distinguish descriptor ownership, kernel Root return and bank retirement. The [operator guide](../runtime/outbound-stream-operator.md) documents exact canonical policy confirmation and the local adoption fence. Selected rustls 0.23.46 source does not enable direct host TLS: its accounting-qualified guard remains false. |
| Management preparation, state and delivery: #1255, #1263, #1288, #1430 | Existing [composition inspection](../how-to/inspect-a-composition.md), [target inspection](../reference/target-inspection.md) and state/recovery contracts remain applicable. Exact release preparation runs through management ownership; inspection/preparation grants no dispatch authority. The audit does not close collective transaction or packaged recovery gates. |
| Test ownership, CI and diagnostics: #1234, #1332, #1347, #1353, #1379, #1414, #1427, #1443, #1454, #1456, #1458 | Maintained test/CI references already separate source controls, metadata, actual discovery, immutable native tuples, signed programmes and physical cleanup. [VALIDATION](../../VALIDATION.md) now exposes the newer memory, cooperative-profile and kernel/operator owners. `tools/test.py list --output json` identifies 230 plan entries at this snapshot; that is not a discovered or passing test count. Frozen inputs and historical failures remain intact. |
| Dependency security, attribution and website: #1095, #1096, #1099, #1100, #1102, #1103, #1241, #1244, #1420, #1423, #1449 | [Toolchain documentation](toolchain.md) now names Tokio 1.53.3 and the maintained Wasmtime 48.0.7 cohort. The [website guide](website.md) matches npm derivation v5 and current selected overrides. [NOTICE](../../NOTICE) identifies maintained Wasmtime, retained-owner bytes, selected rustls and WASI interface inputs with their original license texts. [SECURITY](../../SECURITY.md) includes those trusted components and narrow native/compiler bridges. |
| Research and architecture navigation | The existing research/RFC contracts remain optional investigations. Cooperative scheduling and native-memory accounting do not implement durable continuation eviction, userfault paging, call-graph fusion, native-SFI or a hardware-capability backend. The [architecture index](../../ARCHITECTURE.md), roadmap and changes guide now expose the current execution and evidence owners without changing research promotion decisions. |

## Review of merges without Markdown changes

The inventory includes all 95 such merges. Many repair exact frozen-source,
formatting, lock or CI expectations and need no separate feature narrative.
Behavior changes still require a contract review: policy confirmation/adoption
(#1392, #1429, #1430), exact management preparation (#1263), retained physical
owners (#1346, #1348, #1351, #1356) and registry cleanup test expectations
(#1456) are covered by the owners above. Source-capture limits and diagnostics
(#1426, #1444, #1447) retain their current implementation and existing bounded
capture/compatibility references. A missing documentation diff was not treated
as evidence that a change had no user-visible consequences.

## Verification and boundaries

Documentation verification uses the repository validator, documentation/link
validator, workspace README/feature/dependency checks, the website's source/type
checks and tests, both production base paths and built-site browser checks.
The PR records the actual commands and results. Metadata inspection selects no
runtime test or compiler job by itself.

This audit does not rerun native compiler, signed-language, kernel/VM, provider,
transaction recovery, scale or soak campaigns. Their original receipts and
failed attempts are evidence for their named products, not a rebuilt current
host. It changes no engine, ABI, admission rule, security gate or test limit.

Frozen released website documentation, accepted ADRs, captured upstream source,
raw qualification products and their source-bound identities are retained.
README additions can change compiler-source capture identities where a recipe
includes their directory; old receipts are not rewritten to match. Historical
material is linked through [engineering records](engineering-records.md) rather
than expanded into another set of per-PR histories.
