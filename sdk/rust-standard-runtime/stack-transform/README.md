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

## Package architecture

`latent-rust-std-stack-source-transform` is an isolated Rust library with its own
[Cargo.toml](Cargo.toml), [Cargo.lock](Cargo.lock) and empty local workspace. It is
outside the root's 52 members. Its direct dependencies are the pinned Wasm parser,
encoder and SHA-256 implementation; it has no path dependency on the node,
capability broker or activation executor.

| Source / interface | Responsibility |
| --- | --- |
| [src/lib.rs](src/lib.rs): `transform` | Check the exact original preimage and supported core-module shape, rewrite actual stack-global instructions, append helpers and validate the output |
| [src/lib.rs](src/lib.rs): `Receipt` | Preserve original/derived hashes, original stack identity, rewrite counts and explicit debug/profile qualification flags |
| [src/thread_entry.rs](src/thread_entry.rs): `transform_owned_thread_entry` | Rewrite a selected owned-thread callback through an appended translated body and checked context attach/detach wrapper |
| [src/thread_entry.rs](src/thread_entry.rs): `ThreadEntryReceipt` | Bind original/derived module identity and the selected callback/wrapper transformation |

## Transformation and ownership boundary

1. The caller supplies immutable core-module bytes and their expected digest.
   Preflight checks the selected module/import/global/memory profile and finite
   input/function/operator bounds before re-encoding.
2. The transform preserves original indices and unrelated sections. It rewrites
   code operators, rather than scanning data or custom sections for matching
   instruction bytes.
3. Appended stack helpers require the already bootstrapped canonical context.
   The owned-thread variant retains the original callback identity while moving
   its body and enforcing the checked entry/exit protocol.
4. Output validation and a receipt bind the derived bytes to the original input.
   The caller still owns buffers, profile selection and every real runtime,
   stack, TLS, native fiber and accounting object.

The returned bytes/receipt confer no execution authority. A valid transformed
core module is not a fully composed component or proof of supported Rust threads.
The existing source limitations above remain prerequisites for any promotion.

## Source tests and development

Unit tests live alongside both implementation modules. They cover actual
stack-get/set replacement, untouched data/custom bytes, wrong preimages,
missing/wrong context, unsupported stack/memory shape, stackless helper behavior
and owned-thread wrapper structure. These are transformation/validation tests,
not signed guest execution or safe-preemption evidence.

This project is not selected by the root registered test inventory. Use its
independent manifest/lock and the Rust standard-runtime investigation's selected
toolchain; changing the root feature set does not enable this experiment. A
source change needs both transform checks and the separately qualified consuming
runtime before it can claim application support.

## References

- [Rust standard runtime investigation](../README.md)
- [Rust guest qualification](../../../docs/development/rust-capsule-qualification.md)
- [Invocation-scoped runtime ownership](../../../docs/runtime/activation-runtime.md)
- [Continuation eviction research](../../../docs/runtime/continuation-eviction-research.md)
- [Workspace and isolated package index](../../../crates/README.md)
