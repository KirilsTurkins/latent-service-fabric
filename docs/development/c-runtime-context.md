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
and six new C mechanism controls, then this compiler control. The exact
[e6e52433 run39408486561/job118580143884](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/39408486561/job/118580143884)
passed all26 Rust cases and the compiled C/core-Wasm control. The
[source-bound observation](../testing/evidence/c-context-mechanism-2026-10-20.json)
records artifact12258655842 (8,635 bytes), all24 member digests, all9 exact
Git input identities and an independent replay of the retained core under
pinned Node. The actual C root/child records retain separate TLS counters
8/9 then9/11 and stack addresses65472/131008, including callback reentry and
all six invalid-context traps. The original untransformed output fails isolation;
ordinary static lowering is concretely refused for absent TLS-base export.
This remains a compiler mechanism control, with no canonical child or native
runtime execution and no pthread-profile qualification. It builds only the small parser/encoder tool, with no
native engine or application build. C ABI creation/join/identity, errno and key
TLS destructors, mutex/condition/timed waits, CPU checkpoints, ordinary sockets,
root draining, cancellation and cross-tenant physical reuse still require their
own implementation and signed qualification before any #744 criterion closes.

The next explicit source-only PAL, `sdk/c-guest/runtime/tls-keys.c`, supplies
ordinary WASI-musl `pthread_key_create/delete`, `pthread_get/setspecific` and
`errno` entry points beneath the selected compiler context mechanism. It has
128 per-Store key slots, generation-encoded handles and per-context values.
Deleting a key never invokes its destructor; reusing a slot cannot expose an
old context's stale value. Generations never wrap: exhausted slots retire.
The registry's fixed operations must remain non-suspending SDK critical code;
there is no lock protecting it against arbitrary scheduling instrumentation.
No maintained builder links this PAL, and no OS-thread safety is advertised.

The internal closing hook clears each value before invoking its destructor,
allows values to be reinstalled and runs at most four passes. Recursive closing
returns `EDEADLK`. A cyclic destructor leaves its pending value owned and returns
`EBUSY` after the fourth pass; the future runtime must retain/quarantine that
owner rather than treat the hook as physical retirement or refund resources.
Ordinary pthread key functions return their error codes without changing errno.
Both direct WASI-musl errno and `__errno_location` address the selected context.
No C11 `tss_*`, thread creation/join, cancellation unwinding, destructor suspension
or native owner accounting is supplied by this slice.

The focused compiler controller retains all original controls and adds a real
compiled-core key/errno control: callback reentry into a second context, stale
key deletion/reuse, the 128-key ceiling, independent destructor state, clearing
before callbacks, bounded reinstall passes and retained cyclic pending state.
It uses the pinned Zig WASI-musl headers with an explicit aggregate identity;
no libc thread stubs or ambient runtime are linked.

The exact [577492a0 run39413924006/job118598192794](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/39413924006/job/118598192794)
passed all26 Rust controls, the original C isolation/refusal control and the new
compiled TLS-key/errno control. The [source-bound observation](../testing/evidence/c-tls-keys-mechanism-2026-10-20.json)
authenticates artifact12261121042 (14,640 bytes), its complete archive SHA-256,
all35 CRC-checked members, all12 Git source rows and all8 product identities.
An independent replay of the retained derived TLS-key core under Node24.19.0
passed the same exact public assertions. The pinned WASI-musl header inventory
contains343 files/733,646 bytes; compiler implicit inputs remain unattested and
producer tool binaries were not independently retained.

These actual controls establish the finite compiled-core mechanism only. No
canonical child, signed component, production node or libc thread lifecycle
executed. This does not qualify the complete pthread profile or close #744.
