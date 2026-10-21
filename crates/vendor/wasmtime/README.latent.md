# Pinned dynamic component-value allocation admission

This is the complete crates.io Wasmtime 48.0.7 package, licensed under
Apache-2.0 WITH LLVM-exception (see the unmodified LICENSE). The original
archive checksum and all 250 original file identities are recorded in
UPSTREAM.latent.json. `latent-dynamic-memory.patch` applies to that exact
original package; it contains the six changed upstream files and two added
implementation files. Other Wasmtime packages remain at the original locked
registry versions.

The maintained extension is `component::DynamicValueMemory` and
`Func::call_async_with_memory`. It admits actual allocation capacity in the
selected ordinary dynamic-value surface before allocating. It does not replace
the global allocator. Existing dynamic entry points do not install this hook.
Unsupported resource/map/fixed-list/future/stream/error-context values are not
admitted by the extension. Existing canonical pointer/alignment/encoding checks
and hostcall fuel remain active; a string sizing prepass does not consume fuel
again.

Original allocation scopes follow actual values. The concurrent parameter copy
has a separate refundable scope; its Vec is destroyed before its scope. Queued
results retain their shared original scope through Store-owned work and caller
abandonment. After result values move into the caller's already prepaid slots,
the physically retired temporary Vec and Any-result Box are refunded. The
caller must retain its shared scope until its actual output values die.

Exact-capacity Vec construction uses the pinned Rust Global/RawVec allocator
layout, checks exposed capacity, and includes 64 bytes of finite allocation
bookkeeping. String destinations are allocated once after bounded UTF-8 byte
counting; UTF-16 and Latin-1 do not create an intermediate decoded String.
Flags growth admits replacement and original buffers simultaneously, then
refunds the old buffer only after physical destruction. Partial lift failure
retains confirmed actual allocations through native unwind, without confirming
a hypothetical signature maximum as observed peak.

The native cohort is
`wasmtime-48.0.7-latent-dynamic-value-memory-v1`. Runtime engine configuration
identity includes this cohort, so old prepared/AOT identity cannot certify the
new host. The native programme retains the original 52 controls and adds six
actual engine allocation controls, one linked-child journal retirement control and
two selected C public async-type/synchronous-Core admission controls. This source package is not itself evidence
that any control executed or that the whole host/transport resource contract is
complete.
