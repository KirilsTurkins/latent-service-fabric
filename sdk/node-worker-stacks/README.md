# Node-owned worker stack profile

The standalone node's control and invocation Tokio builders share one checked
profile. Worker and blocking-thread maxima retain their existing configuration
limits; control can have two blocking workers when rollouts coexist with policy
or provider work. The old topology assumed one and undercounted this case.
Every thread now requests an explicit 2 MiB stack instead of inheriting an
ambient/platform default. An additional 64 KiB per live or possible thread is
reserved as a finite guard/alignment envelope. Topology byte rows describe these
NodeFixed reservations, not measured resident memory. Actual start/stop counters
retain the live-thread observation while a timed-out runtime still owns a live
blocking operation. The configured NodeFixed capacity is never refunded by a
callback count. On normal completed shutdown Tokio joins its thread handles; its
stop callback precedes final thread return, so callback zero after a timeout is
not proof of OS stack unmapping. Allocator/pthread stack caches also remain
outside the live-thread observation.

Wasmtime's ordinary 512 KiB Wasm limit/2 MiB async fiber and the renderer's
2 MiB/4 MiB policy are separate existing fiber allocations. They are unchanged
and remain charged by their existing activation/instance owners. This profile
covers Tokio's node-owned worker mappings, not compiler workers, epoch helpers,
the initial process stack, every host stack or all process memory.

The small Linux reference compiles the exact shared production builder and its
five controls with a fixed 16-package registry closure identical to maintained
Cargo.lock. It sets RUST_MIN_STACK to 8 MiB before process startup. A guarded
one-line derivation removes only explicit thread_stack_size to reproduce the old
ambient-stack behavior and must fail the actual mapping control. The unchanged
current source must pass all five named controls, observing two workers and two
blocking threads, a nonzero contiguous inaccessible guard, bounded mappings and
actual retained ownership after a shutdown timeout. Only numeric sizes and fixed
labels are retained; no addresses or /proc maps are exported.

Preparing this lane is not execution. Its actual receipt binds every source and
both executables before/after. It does not qualify a complete latentd build,
TLS verification on the composed node, allocator bounds, kernel TCP resources,
#738/#739/#740 or production enablement. ACCOUNTING_QUALIFIED remains false.
