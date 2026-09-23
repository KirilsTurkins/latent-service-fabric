# Java guest authoring: feasibility and implementation boundary

Issue: [#548](https://github.com/KirilsTurkins/latent-service-fabric/issues/548).
Baseline inspected: `34f03fad155c1f35efc3b7a1510726dbc04fc3c5` on `development`.
Review date: September 23, 2026.

**Status: incomplete; neither maintained compiler candidate is qualified.**
The feature branch adds research scaffolding and harness tests, not the required
Java guest authoring implementation. It must not close #548, satisfy the six-
language Phase 3 gate, or remove the runtime release hold. No failed LSF execution
is claimed: no Java candidate was executed in LSF in the retained local run.

## Upstream boundary

The [wit-bindgen Java section](https://github.com/bytecodealliance/wit-bindgen#guest-java)
records removal of its unmaintained TeaVM-WASI generator. Its historical presence
is not current guest Java support. The probe never downloads or revives it.

[TeaVM release notes](https://github.com/konsoletyper/teavm/releases) identify
0.15.0 as a maintained release and record removal of the old Wasm/WASI targets
in 0.14.0. The pinned
[`TeaVMTargetType` source](https://github.com/konsoletyper/teavm/blob/0.15.0/tools/core/src/main/java/org/teavm/tooling/TeaVMTargetType.java)
contains `JAVASCRIPT`, `WEBASSEMBLY_GC` and `C`. This experiment selects the latter
two; it does not call either of them an LSF-supported profile.

The [C backend documentation](https://teavm.org/docs/c-backend/getting-started.html)
describes generated C compilation. The candidate path is Java -> TeaVM C ->
Zig/Clang Wasm -> a still-missing maintained canonical ABI bridge. Compiling the
upstream C runtime for WASI, providing only authorized imports, and maintaining
async ownership are unresolved engineering work. A native C executable would
not itself satisfy the ticket.

The [Wasm-GC loader documentation](https://teavm.org/docs/wasm-gc-backend/loader.html)
describes the JavaScript loader and its host imports. Raw Wasm-GC output is not
therefore an LSF component with WIT-generated imports/exports. A qualified path
would need to eliminate or explicitly implement those dependencies without
ambient browser/JavaScript authority, then provide the canonical ABI bridge.
This report does not assert that Wasm GC is categorically unsupported by Wasmtime
or that such a bridge is impossible.

## Relationship to current LSF

The inspected baseline pins Wasmtime 47.0.4, wit-bindgen 0.62.0 and wasm-tools
1.254.0 in [`tools/toolchain.toml`](../../tools/toolchain.toml). Its
[`surface.rs`](../../crates/latent-wasmtime/src/surface.rs) validates declared
interfaces, actual signatures, provider installation, async function kinds and
resource identities. Its
[engine settings](../../crates/latent-wasmtime/src/config/engine.rs) retain fuel,
epoch interruption and component-model containment.

Those checks are unchanged. The experiment does not introduce a permissive WASI
linker, revive an alpha adapter, install JavaScript loader state, fabricate host
grants, or add a language process/thread to a dormant deployment. It also does
not demonstrate the required dormant-resource invariant: no Java deployment was
created and no guest-runtime measurements were taken.

The existing [`sdk/java-client`](../../sdk/java-client) remains an external Java
RPC client. Its working transport and Java 25 baseline do not count as evidence
for guest authoring. The exploratory `probe.wit` is not a replacement for the
shipping, greeting or word-count contracts.

## Reproduction and retained local evidence

The [probe README](../../research/java-capsules/README.md) contains prerequisites,
commands, expected outcomes, common failures and cleanup. The machine-readable
[local validation record](../../research/java-capsules/evidence/local-validation.json)
retains actual command results and SHA-256 identities of the local research
sources tested. It is not a signed build observation or package attestation.

At the time of this change:

| Check | Observed result | What it does not establish |
| --- | --- | --- |
| Python harness tests, Python 3.13.5 | 31 tests passed | Most compiler behavior is injected; no TeaVM/LSF conformance. |
| Feature corpus on available Java 21.0.11 | 14 local checks passed | Not the pinned Java 25 baseline and not Wasm execution. |
| Same source with `javac --release 25` on available JDK | Exit 2: release version 25 not supported | A missing local prerequisite, not a Java-to-Wasm compiler blocker. |
| Gradle, wasm-tools, wit-bindgen, Zig and Cargo in the execution environment | Not installed | No candidate compiler or real-node execution result is available. |
| TeaVM driver / Gradle recipe | Source reviewed; not compiled or executed | Neither compiler candidate can be called working or failed from this local run. |

The runtime/toolchain source was inspected through the connected repository API;
the local execution directory contained the new research files, not a complete
repository clone. Consequently the full probe command was not represented as a
valid repository attempt. The local validation record is deliberately narrower.
A complete checkout and pinned tools are required to produce a full `report.json`.

The standalone research suite is **not integrated into required CI**. Existing
repository CI running on the PR is not a substitute for the missing compiler,
binding-drift and real-node conformance lanes. No CI pass is claimed by this
report. A required CI integration will also need reviewed updates to
`tools/ci/commands.json` and the affected suite/recipe inventory.

## Candidate result matrix

| Candidate | Current evidence | Qualification status |
| --- | --- | --- |
| Removed TeaVM-WASI generator | Removal documented by upstream; no obsolete implementation reused | Excluded, not a fallback |
| TeaVM 0.15.0 C -> Wasm | Executable experiment source added; build not run | Unqualified |
| TeaVM 0.15.0 Wasm GC | Executable experiment source added; build not run | Unqualified |
| JavaScript output in an application-owned runtime | Not implemented or proposed by this change | Does not satisfy this delivery boundary |

A reproducible compiler failure needs a complete attempt directory containing
source/tool identities, the exact command, exit code and diagnostics. A missing
tool, network failure, malformed experiment, or incomplete raw bridge must not
be restated as proof that Java authoring is impossible. The harness distinguishes
infrastructure failures from actual command failures and never marks the issue
complete even after all commands pass.

## Work still required before claiming #548 delivery

| Requirement area | Missing implementation/evidence |
| --- | --- |
| Maintained compiler/component path | Resolve candidate runtime/GC and host imports; qualify on the actual current LSF engine. |
| WIT-generated Java bindings | Generate authoritative imports and exports; explicitly reject unsupported contracts rather than changing semantics. |
| Value/error semantics | Prove full-width integers, UTF-8, lists, records, results, resource identities and Java exceptions versus declared WIT errors across the actual ABI. |
| Async capability ownership | Implement buffered/streaming HTTP, blobs, secrets, events, local services, randomness and metrics; exercise each wrapper's close/drop, authority, budgets and cancellation without uncertain-effect retries. |
| Complete examples and project template | Match authoritative greeting, word-count and shipping contracts, valid/invalid outcomes and allowed/denied capability use. The compiler corpus is not this deliverable. |
| Package and deployment workflow | Derive metadata from actual source/component/WIT; package, sign, publish, admit, deploy, invoke and clean up on a real node. |
| Runtime containment and resources | Exercise deadlines, cancellation, traps, memory/resource exhaustion and fresh subsequent state; measure startup, active heap/GC, bounded caches and cleanup. |
| Dependency/binding reproducibility | Pin and verify the full resolved graph and tools; add generated-binding drift and meaningful required conformance CI, preserving unsuccessful attempts. |
| User documentation and completion review | Publish a supported language profile and verified newcomer commands, complete #345 review, then link final source/CI/execution evidence before closure. |

There is no supported reflection, dynamic-loading, class-library or dependency
compatibility promise yet. The corpus's standard-library calls are test inputs,
not a declaration that those APIs work in a guest. Java exceptions are tested
only inside the local corpus; no mapping to a WIT `result` has been implemented.

The next implementation must select and qualify a maintained bridge, rather than
removing the unfinished items from this report or changing its `canCloseIssue`
flag. Merge readiness and Phase 3 completion remain separate from successful
research-harness tests.
