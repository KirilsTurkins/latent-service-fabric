# Separate post-stage Java diagnostic source

The maintained diagnostic creator and explicit single-component compiler plan
retain the original aggregate WIT, legacy schema, companion, finite limits and
27-byte put-once requirements. The original default two-component compiler plan
and explicit three-schema plan keep their existing component sets. The five
components retained in [the earlier compiler receipt](../java-transaction-compiler-r3/README.md)
are unchanged.

The [JVM receipt](receipt.json) records the actual pinned Temurin 25.0.4.1
compiler, helper source hashes and four successful helper vectors: ordinary,
controlled trap, reuse refusal and a distinct fresh ordinary JVM. Its original
bounded stdout/stderr files are retained alongside the receipt. These vectors
test helper semantics; they do not prove Wasmtime instance freshness, transaction
staging, fuel exhaustion, cancellation or signed node execution.

Thirteen focused Python source/compiler/schema cases passed. The two new source
cases preserve exact original ABI, limits and authority inputs, reject staging
drift, and refuse replacement of an existing capture. The new compiler case
refuses non-Java, implicit or combined plans and preserves a failed diagnostic
capture without claiming compilation. All five prior compiler cases and their
execution guards remain unchanged. The reviewed Java job retains all previous
commands and adds bounded JVM vectors plus this explicit unsigned component.

The actual TeaVM component and native transactional assertions in the
[fault-capsule schedule](../../testing/java-transaction-diagnostics.md) are pending.
No guest-selected persistence, retry, provider, credential, namespace or effect
authority is introduced by this source milestone.
