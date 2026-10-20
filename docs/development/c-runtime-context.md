# C compiler stack and TLS context mechanism

Issue #744 remains open. This explicit source transform is never selected by a
builder or engine and does not establish pthread, C11-thread or standard I/O
compatibility. No runtime profile, grant or language default changes.

The pinned Zig 0.16.0 / Clang 21.1.0 ordinary non-threaded wasm32-wasi lowering
turns `_Thread_local` into fixed process-data addresses. The explicit `-pthread
-matomics -mbulk-memory` lowering retains `__tls_base` accesses even when the
linked memory remains unshared. The unshared linker exports an immutable initial
TLS base and does not supply `__wasm_init_tls`, `__tls_size` or `__tls_align`.
Consequently the transform requires the actual retained TLS accesses, a linked
core module, finite unshared memory32, original canonical context-get import,
immutable TLS/data-end layout globals and an exact source preimage. Shared
memory, actual atomic instructions, absent lowering, relocation objects and
core start functions are refused. Enabling target atomics is not approval of
any C11 atomic operation or compiler memory-model mapping.

The source mechanism replaces actual SP gets/sets and TLS-base gets with three
stackless helpers. Original function indices, calls, imports, globals, data and
custom sections remain. Helpers read only the currently selected canonical
context: no global current-thread variable or common mutable TLS base is
installed. Missing/misaligned/non-running contexts, committed stack-pointer
crossings, mismatched TLS extent and out-of-memory TLS bases trap. The original
custom debug offsets remain original; no relocated debug-map claim is made.

The 32-byte experimental record stores SP at 0, stack low/high at 4/8, TLS base
at 12, charged template extent at 16 and phase at 20 (2 means running). The
remaining bytes are reserved. The template extent is the complete linked data
tail from `__tls_base` through `__data_end`, capped at 1 MiB; it can include
ordinary data and is an upper bound, never an exact TLS memory measurement.
A future authenticated bootstrap must capture that immutable template before
constructors, validate every object/archive TLS alignment and allocate/charge
all context/stack/template bytes before admission. These duties are not supplied
by the transform. TLS over-alignment, inter-region non-overlap, stack growth and
physical native stack retirement remain unqualified. Leaf C frames can use
SP-relative storage without a global SP write; any future suspension checkpoints
must precede code generation or otherwise prove complete live-frame coverage.

`tools/qualify_c_context_lowering.py` compiles only a fixed C mechanism fixture
and executes its actual transformed core through pinned Node 24.19.0. Its test
callback explicitly selects two separate records and reenters ordinary compiled
C while the first C frame remains live. Independent TLS initial values, both
stack frames, restored root TLS, successive calls and six invalid-context cases
are checked. The original untransformed core must fail the same isolation
control. The ordinary non-threaded compiler lowering must be refused by the
transform. All inputs/tools and products receive SHA-256 identities and are
checked after execution. The finite controller runs at most 180 seconds and
retains failure records. It executes no canonical child, signed component,
production node, dependency library or libc thread implementation.

The focused workflow runs the original twenty Rust parser/transform controls
and six new C mechanism controls, then this compiler control. Actual hosted
execution is pending. It builds only the small parser/encoder tool, with no
native engine or application build. C ABI creation/join/identity, errno and key
TLS destructors, mutex/condition/timed waits, CPU checkpoints, ordinary sockets,
root draining, cancellation and cross-tenant physical reuse still require their
own implementation and signed qualification before any #744 criterion closes.
