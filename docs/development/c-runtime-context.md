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
The original pthread-only slice did not supply C11 `tss_*`, thread creation/join,
cancellation unwinding, destructor suspension or native owner accounting.

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

The additive C11 source slice supplies ordinary `tss_create`, `tss_delete`,
`tss_get` and `tss_set` using that same key registry, context values and closing
hook. It requires the pinned WASI-musl key ABI and `TSS_DTOR_ITERATIONS == 4`.
Creation/set return `thrd_success` or `thrd_error`; deletion returns void and
runs no destructor. C11 and pthread calls share the128-slot ceiling and retain
generation/stale-value protection. Error returns preserve context errno.
There is no second registry, value array or destructor budget.

The new fixed C11 fixture uses the ordinary public headers and entry points.
Pinned Clang rejects the original PAL for four unresolved `tss_*` symbols and
links the new PAL with the same4MiB maximum memory and64KiB stack.
[Run39490031609/job118860442491](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/39490031609/job/118860442491)
passed the actual compiled-core C11 cases: root/child context isolation, deletion
without callbacks, shared pthread/C11 exhaustion, error returns, stale handles,
bounded/reentrant/cyclic destructors and context errno. The
[source-bound original receipt](../testing/evidence/c11-tss-core-2026-10-20.json)
retains the original report and all44 member identities for artifact12296081910
(19,765B; SHA-256 `9d25dc0ce5d68e80cd7108f5c6c41fa9775e6af27ef8b4bc6903aecfaf837985`).
Independent review authenticated all14 Git sources and11 products and replayed
the retained C11 core under the same Node24.19.0 public assertions.
All original26 Rust/parser, C isolation/refusal and pthread controls remain.
This C11 source addition does not select a production thread profile or supply
thread creation/join, canonical children, charged bootstrap, synchronization,
checkpoints or signed/native physical retirement. #744 remains open.

## Ordinary creation and guarded bootstrap source

The next unselected source slice is
`sdk/c-guest/runtime/threads.c`, with its fixed memory32 ABI in
`thread-abi.h` and `thread-abi.json`. It supplies ordinary
`pthread_create/join/self/equal` and `thrd_create/join/current/equal` beneath
unchanged application calls. A successful creation requires a real canonical
child. That child installs its own context, checks its actual canonical
identity and yields to its creator before executing the user start function.
The creator does not execute the worker inline or manufacture a successful
handle. A deliberate refusing entry remains until the compiler transform
authenticates and replaces its exact original bytes.

This is source infrastructure. No maintained builder or production engine
selects it, and no canonical child or signed runtime has qualified it. The
hosted source run below supplies executable transform-unit evidence. The original Rust context40 transform, component verifier
and engine profile remain unchanged.

The C context keeps the existing32-byte SP/TLS prefix. Its144-byte aligned
record also holds original activation Task/Native/Result tokens, a single-use
creation state and typed pthread/C11 start/result fields. Root ownership is
lazy. Child Task, Native and Result admission precede allocation of the
context,64KiB C stack and conservative TLS image. The fixed creation wrapper
calls the original native broker with the child's Task token before the sole
canonical creation instruction. An error before creation frees only unstarted
allocations and settles their logical owners. A trap or uncertain creation
cannot be treated as successful retirement.

The32-record registry is an implementation bound, not a new runtime Task or
native-stack quota. The original broker and Wasm-memory limits can refuse
earlier. Handles are registry-owned context identities; tombstones are not
reused during an activation. A join has one joiner and an original Wait
owner, parks only its caller and switches the actual child. Unknown, self,
duplicate, API-mismatched and cyclic joins cannot return success. Only the
fixed child epilogue may establish completed C/TLS frames and detach context.
Join may then release C stack/TLS allocations and logical owners; cached
physical native-stack reservations remain charged through Store destruction.
Root cancellation or a trap does not fabricate a completed join.

`c_template.rs` reconstructs the original pre-initializer TLS image from
actual active data segments in module order, including overlapping writes and
zero-filled gaps. Original passive data is not guessed to have initialized
memory. The new private passive image and fixed stackless `memory.init` copy
retain all other original sections, functions and data encodings. Every
original active segment must fit initial memory. The private image cannot be
dropped or referenced by any other function. Only TLS-relative accesses are
redirected: copying the conservative linked data tail does not make ordinary
shared C globals thread-local.

The measured LLVM layout puts an ordinary initialized C global after
`__tls_base`, inside that conservative copied tail. Consequently the root
record is not a normal C global. `c_root.rs` instead requires an authenticated
4KiB low guard and an unchanged64KiB usable root stack at `[4096,69632)`.
The aligned144-byte root record occupies `[16,160)` inside that guard, within
the original memory ceiling. Final core bytes must show no active data in the
guard or root stack, TLS at or above the stack high bound and the heap at or
above the TLS tail. Start functions and separate reactor initializers are
refused; the required exported original `__wasm_call_ctors` body must be empty.
Constructor support is not inferred from an absent symbol.

The root transform recomputes the entire template/child chain from one
authenticated original. Its fixed wrapper installs context before calling
ordinary C initialization or the original selected public function, retains
the original flat return values, drains accepted children and TLS state, then
checks the restored stack before stackless detach. An unexported one-use
global prevents a second root entry. Every original body and section remains
bound alongside the precise new wrapper, global and export route.

The selected compiler must still authenticate every object/archive's TLS
alignment, protect allocator and registry critical regions, preserve all
stack accesses and supply final whole-component canonical routing proof for
this separate C layout. Ordinary C can corrupt its own linear memory; these
records do not replace host admission or final-byte routing verification.
The finite root fixtures use scalar core arguments. Canonical string lowering
may execute C `cabi_realloc` before the public root, and post-return may execute
C after it. Those paths need their own authenticated context lifecycle before
an ordinary string component can select this port. The bootstrap-only API does
not supply those scopes; the separate C ABI derivation below is still unselected.
Non-default attributes, detach, `pthread_exit`, cancellation unwinding,
setjmp/longjmp, C++ dynamic TLS, mutex/condition/timed waits, CPU checkpoints,
atomics and standard I/O are outside this source slice. Their absence cannot
be counted as full #744 support.

[Run39545094659/job119041367915](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/39545094659/job/119041367915)
passed all40 exact Rust controls at source065623b99069, including all26 original
cases and14 new C layout, admission, immutable-image and guarded-root cases.
The unchanged controller also passed the existing actual compiled C, pthread
key/errno and C11 TLS controls. The [source-bound observation](../testing/evidence/c-thread-bootstrap-source-controls-2026-10-21.json)
records artifact12321705701 (19,757B), all44 CRC-checked members,14 original
controller source rows and11 products. The three new Rust modules are bound
separately to the actual job's checked-out Git source and exact case log; they
are not invented source rows in the old controller's receipt.

The first hosted attempt39544590130 failed during parser API compilation,
before any controls. The correction uses the pinned parser's public readers
and checked byte ranges; that failed attempt is retained without passing
credit. A local ordinary libc link attempt exceeded its90-second limit and
produced no linked core; it was stopped and not retried locally. Consequently
this observation does not claim execution of ordinary create/join calls, a
canonical child, a production node, whole-component C routing or a qualified
threading profile. Tool binaries and compiler implicit inputs are not
independently retained by this artifact. No #744 checkbox closes from this
finite source slice.

### Separate C canonical ABI source bridge

`c_abi.rs` extends the source derivation for the actual ordinary sync C ABI.
The generator's implementation prototype, result area, exported core signature
and post-return body are retained. It does not rename a sync C function to an
async callback or interpret a callback status as a user result. The public root
still calls the original generated wrapper and drains accepted children before
returning its original numeric flat result. Blocking I/O and an async export ABI
are outside this finite source profile.

The fixed `_initialize`, `cabi_realloc` and corresponding `cabi_post_*` wrappers
open private, nonreentrant System scopes before or after the ordinary C root.
Only the exact stackless SP/TLS helpers can select the original root stack and
TLS base within such a scope. Initialization, ordinary root execution and
post-return retain the same original TLS bytes, including an allocator's real
errno/OOM path. No additional TLS allocation, memory limit or native allowance
is introduced. While a root or child is live, canonical reallocation uses that
thread's current checked context instead.

Every System path has a bounded, transitive direct-call closure. Imports,
thread/context/TSS operations, indirect/reference calls and tail-call escape
are concrete refusals, including on failure branches. The two SP helpers and
TLS helper are the only special terminals and retain their original checked
context bodies outside the private scope. Each System exit checks the restored
64KiB root stack. Initialization and post-return are one-use. Nonzero-size
canonical allocations must return aligned bytes wholly inside original memory
and at or above authenticated `__heap_base`, beyond guard, stack and TLS;
the generator's size-zero sentinel remains valid. A trap leaves the scope
closed to further success, with production containment/Store destruction still
responsible for cleanup. The standalone core control does not model component
Store lockdown after a trap and uses a separate instance for each negative.

The C-only `verify_c_component_routing` consumes the original linked-core
preimage and actual normal encoder output. It recomputes the entire C chain,
requires exact executable/data sections, and permits only consumed
`component-type` metadata and its authenticated original producer merge.
The pinned C generator's0.259/0.62 identities are distinct from the normal
encoder's0.254 shim identity. It authenticates the four finite
main/thunk/fixup/start-shim modules,
the original initializer route and ordering, one sync public lift, memory,
realloc and post-return identities, native admission, sole raw creation and
actual canonical context/index/yield bindings. Private raw/thunk escapes,
additional starts, unknown modules and an async/callback ABI are refused.
Normal staged-world/export verification remains mandatory; this compiler
preimage proof is not an autonomous host profile selector. The original Rust
entrypoint and its three-module profile keep their separate verifier path.

Read-only replay of historical C run39413019080/artifact12259784236 verified
all161 ZIP members and regenerated its three original binding outputs exactly
with `wit-bindgen`0.62.0. The actual string component has `_initialize` through
the normal start shim, a `(i32,i32)->i32` entry and `i32->()` post-return. A
metadata-only embed/component-new replay changed only the pinned producer
version; all other18 main-core sections were exact. Those are historical data
observations, not execution of the new threading source.

The new canonical-ABI fixture uses ordinary pthread/C11 calls beneath an
unchanged generated `bool` implementation prototype and real string Err/Ok
results. Hosted run39551488404 at2fac08a passed all46 Rust source cases and the
existing actual C controls. The new link then refused the unsupported Zig0.16
linker argument `--stack-first` before producing a core. Artifact12323601938
retains all71 members and the failed stage; its archive SHA-256 is
`0e74ca8be668114b55fff277d37fb3ba51bec2648379b8362f319f08df0e7120`.
The correction removes only that unsupported argument, keeping the supported
stack-size69632 option, original4MiB memory ceiling and every final-byte layout
check. Actual selected linking, ABI/OOM execution and final graph authentication
remain pending the corrected hosted control. No engine, builder, host grant or
threading profile selects this path, and no additional #744 criterion closes.

The corrected run39552433461 retained another concrete link failure: both the
standalone PAL and original WASI libc defined `errno`. Artifact12324491302 has
71 authenticated members and archive SHA-256
`72cd6d8b82777d62f485c4d6434b4d9f458a25af79006affcf7ce94ad97fb083`.
The internal `LSF_C_LINKED_LIBC=1` mode leaves both errno storage and its location
function to the original linked libc. Its thread-local accesses still pass
through the same whole-core context derivation. The existing no-libc controls
retain their original fallback definitions. Five preprocessing-only controls
confirmed exact standalone output, an external TLS declaration in linked mode,
and refusal of invalid mode/header families; they did not link or run a core.
The linked source/header preimages are checked before and after the programme.

Run39553398769 at1a0e01d linked the ordinary C core in20.99seconds and passed
ABI derivation, normal component encoding, validation and final WIT checks.
The final graph reader then refused its incorrect0.254 main-producer
expectation. The original embedded generator metadata actually contributes
`wit-component`0.259.0 and `wit-bindgen-c`0.62.0 to the encoded main module.
Artifact12324403326 retains85 authenticated members (archive SHA-256
`aed1d69aefa9a6e91b19497306e621edf6bf0297e6463938fdb724c48f0a949f`).
Read-only comparison verified all21 other main sections exactly and six adverse
metadata/data mutations were refused. The corrected reader derives that exact
merge from bounded, pinned original metadata and preserves all other fields;
its two new Rust controls and actual graph/ABI/OOM programme remain pending.
The original failed job and its unexecuted ABI control are not counted as a pass.
The first reader retry39554864662 failed before controls because its extracted
offset parameter used `usize` instead of the pinned parser's `u64`. It emitted
no artifact. The correction changes only that parameter type.
