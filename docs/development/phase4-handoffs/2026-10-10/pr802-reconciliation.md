# PR #802 Java guest compiler reconciliation

## Issue and comment review

PR #802 contributes to
[#718](https://github.com/KirilsTurkins/latent-service-fabric/issues/718), the
Java guest slice of #389. It closes no ticket. The issue requires actual signed
Java state/query/intent execution, HTTP recovery, crash/retention and bounded
cleanup evidence. External Java client tests and compiler captures remain
separate evidence.

The review includes both #718 comments and comments on #382, #384–#386,
#387–#391, #393, #397–#400, #402–#403, #406, #408–#409 and #708. The October 8
comments preserve stopped checkpoints; they do not override the current request
to resume. Current issue state takes precedence over older progress text:
#382/#384/#385/#386/#393/#708 are closed. The remaining installed guest, HTTP,
restore, browser and distribution criteria retain their owning tickets.

The original head is `7501e63944976871fbd51fb8a8ba6de6bf18f9c4`. Normal integration
of development `83dddbdae50ef17fb1768cf8a8184f004417961d` preserves the delivered
affine admission/completion and qualified deferred HTTP owners, plus the current
retention, authorization, test inventories and six external clients.

## Source and snapshot decisions

The Java guest generator/SDK and shared transaction substrate are already in
development through the earlier delivered PRs. This continuation retains the
captured clock declaration, profile-aware compiler compatibility checks,
explicit Java schema and post-stage diagnostic fixtures, and their maintained
compiler CI paths. The existing Rust result-boundary variant remains intact.
Fixtures describe requested application behavior and grant no runtime authority.

#968 preserves earlier compiler captures. #977 preserves the dependency and
renderer batch already present in #802; it is not merged as an older tree.
#851 retains the separate schema-conjunction/runtime checkpoint. #823/#828 and
#879 retain installed state/RPC/HTTP and signed query/recovery continuation.
The older parallel runtime/restore stack and second HTTP adapter remain in those
checkpoints; this PR preserves current development's implementations. Historical
Java compiler evidence retains its original source and qualification flags.

## CI and compatibility repairs

The old exact-source native installer failed before compilation because its
shared-license policy covered Wasmtime 48.0.4 and omitted Cranelift 0.135.5.
The new policy entry binds every affected published crate to Wasmtime's exact
`563544c6296610b1b3fbbe2e4643f9999899ec66` revision and the existing LLVM-exception
license digest. Donor checksum, repository, SPDX declaration, VCS revision and
license-text verification remain enforced. The complete selected Linux inventory
now verifies 294 packages and 458 license files.

The retained dependency batch uses Wasmtime 48.0.5, hyper-util 0.1.21 and cache
restore 6.1.0. Renderer preparation uses ComponentizeJS 0.23.0, jco 1.35.0 and
the explicit Preview 2 shim 0.26.0. The native renderer compatibility identity
and current guide now match those tools. The existing renderer budgets and
weval override remain intact. Historical failure/version observations stay
attributed to their original versions.

Active engine configuration and security schemas follow the exact 48.0.5 pin.
Generated preparation/native/client identities are reproduced through the
maintained generators for all six clients. The Phase 4 WIT ABI digest is unchanged;
prepared artifacts still need current engine/preparation compatibility.

## Current local evidence

Pinned Rust 1.97.1 Linux passes 768 cases across control-store (264), manifest
(17), node (135) and Wasmtime (352). Their three existing ignores remain.
RPC (29) and Rust client (16) suites pass after preparation regeneration.

The actual Temurin 25.0.4.1+1 / Gradle 9.1.0 / TeaVM C / WASI SDK 29 compiler
builds all six components: aggregate, forbidden HTTP, three schema/put-once
variants and the separate post-stage diagnostic. Each component validates its
real WIT surface and retains its captured source, helper and compiler inputs.
These are compiler receipts and do not establish signed node execution.

The renderer builds on pinned Node 24.19.0. Its 24,675,874-byte component executes
in Wasmtime 48.0.5: three fresh renders, reuse and small-memory refusal, ten
bounded failure probes, successful invocation after each failure, and zero live
stores at completion. Browser hydration remains a separate qualification.

Hosted CI is not awaited after push. #718 remains open for the complete signed
Java guest and HTTP acceptance evidence described in its comments and criteria.

All 3,693 maintained Python cases run on pinned Python 3.13.5 Linux: 3,675 pass
and the 18 existing host/tool guards skip. CI coverage preserves 88 baseline
and 280 current required run blocks with 148 delegated owners. Workspace
formatting, foundation, generation and required strict Clippy checks pass.
Historical logs keep their original bytes and source attribution.
