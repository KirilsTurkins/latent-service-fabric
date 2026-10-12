# Canonical shadow-stack source transform

This isolated source experiment rewrites the actual linked Rust core module's
mutable `__stack_pointer` reads and writes into stackless context-backed helper
calls. The canonical thread context at slot 1 must point to an infrastructure
record whose first `u32` is the separately owned, aligned linear stack pointer.
Original function/type indices, unrelated instructions, data and custom bytes
are preserved. New helper functions/types are appended; a missing context traps
instead of selecting the shared stack. Input and output bytes have separate
SHA256 identities; original debug offsets are explicitly unqualified afterward.

The source uses already locked wasmparser/wasm-encoder 0.259.0 and SHA2 0.10.9.
It rejects wrong preimages, non-core/GC inputs, missing/wrong context imports,
unqualified imported globals/memory, shared/memory64/multiple memory and wrong
stack-global shape. Its finite input/function/operator bounds are compiler
profile limits, not replacement activation quotas or per-thread fuel.

This does not create an inline or fabricated thread and is not selected by the
maintained builder. Owned root/export/thread stack bootstrap, exact context/TLS
layout, all entry/exit paths, original ledger admission/native stack accounting,
sysroot rebuild and actual component execution remain required. It is not safe
preemption proof: the pinned dlmalloc wasm backend assumes no threading in its
global lock hooks, so allocator/unsafe regions must not acquire hidden
interleaving from a proposed checkpoint mechanism. Preserve `no_std`/`alloc`
and do not enable broad target features or host-native execution as fallback.

The pinned Rust LLVM22.1.6 linker lacks the newer upstream cooperative-thread
ABI path. A later LLVM option or source design is not attributed to that tool.
The source transform preserves the original core module as an input/preimage
rather than silently rewriting dependency checksums.

The additional owned-thread entry transform keeps the original callback's
function/table index and appends its translated Rust body. Its stackless
wrapper installs the pre-admitted context before calling that body. It requires
TLS cleanup to have finished and the final Rust epilogue to have restored the
owned stack before detaching the context. Checked stack helpers enforce the
context's memory32 range, alignment and live phase. No allocator, owner refund,
parent wake or Rust cleanup runs after detach.

The matching TLS source holds the context/stack owner through the final Rust
frame. It supports separate TLS-finish and parent/reaper retirement phases;
attempting current-context retirement with a live shadow stack fails closed.
Owned stack allocations use System and retire before Native settlement,
including an unstarted or rejected native-reference memory32 allocation.

The exited memory word establishes only that the wrapper's Rust/Wasm frames
returned. Actual native-fiber retirement, root/export bootstrap, Task admission,
std Thread/synchronization/timers/reactor integration and signed component
qualification remain required. The ordinary target still rejects Thread
creation; this source does not fabricate a thread handle or select a profile.
