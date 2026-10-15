# Hardware-capability semantics and evaluation gates

This is experiment design, not an implemented harness or hardware profile.
Use the [LSF source review](README.md#reviewed-lsf-source) and
[primary evidence](upstream-review.md) to identify the actual architecture,
runtime and lifetime assumptions. Keep candidate native code outside the node
until promotion requirements are demonstrated.

## Threat model and distinct authority domains

Initially treat one native parser/computation as hostile. It controls its
instructions, inputs and mutable state and may retain or copy every reference
it receives, trap, exhaust memory or loop forever. Protect the monitor, other
activations, keys, broker policy, resource ledgers and subsequent users of reused
storage. The loader, capability-aware calling convention, entry gates, allocator,
revoker, OS and hardware/tag implementation remain security-critical.

Inventory all initial authority roots: code entry/return capabilities, stack,
heap, data and any default legacy-address authority, thread-local state and host
gate objects. A pure-capability build does not by itself prove a narrow root
set. Hybrid integer addressing must remain confined to the intended component,
not a default data region covering the node. Reachable capabilities in exposed
structures belong to the authority inventory too.

Memory authority alone defines no guest OS policy. Demonstrate how direct
syscalls, mappings, threads, signals and operations returning new capabilities
are mediated or prohibited. A memory-safe request can still ask an overpowered
host service to misuse its authority. Host entry must retain LSF identity,
installation, exact grant, currentness, required audit, deadline and original
accounting owners.
Neither a sealed object nor a copied grant can create another reservation.

State the claimed lifetime level before execution: strict denial immediately
after object free, prevention of access to later reallocations, or an
activation-region isolation contract. A narrower claim cannot borrow evidence
for a stronger one. LSF's subsequent-activation isolation and cleanup obligations
remain mandatory regardless of the allocator's terminology.

## Initial bounded compartment experiment

Select one exact capability ISA/ABI and matching compiler, OS/emulator and
monitor. Begin with a small C function, one input byte buffer, a bounded output
arena and activation-owned stack/heap. Initially exclude guest threads, dynamic
loading, asynchronous callbacks, shared mutable objects and escaped capabilities.
Use a checked host stub only after the memory/entry boundary works.

A standalone C harness may test LSF-like obligations without pretending the
Rust node or Wasmtime has been ported. Supervise it in a disposable environment
with no credentials/network, bounded resources/output and an outer timeout with
actual child reap. Supervisor recovery protects the experiment; it is not proof
of activation-only fault containment inside a node. Do not flash boards, install
a new OS or enable protection registers on the user's host as an implicit part
of this design.

Record actual representable bounds and permissions. Reject an inexact slice or
use a documented private padded allocation charged at its actual footprint.
Do not silently expose neighboring objects. Avoid arbitrary host structures;
use capability-free byte arenas and appropriate capability-load/store controls
where the selected ISA provides them. Test those controls rather than assuming
ordinary read-only permission blocks further capability delegation.

Native capabilities are not portable serialized pointers. Wire/persistent data
must remain ordinary bytes or checked logical handles; a trusted host must not
turn arbitrary decoded address/bounds fields into authority using its own root.
Pin the native calling/return convention, capability width/alignment, code and
data permissions, loader relocations and sealed-object type/activation binding.

## Retirement and safe reuse

The proposed lifecycle is:

```text
active -> guest stopped -> borrows drained or explicitly transferred
       -> old authority inaccessible/revoked -> storage initialized -> reusable
```

Any missing proof leaves the relevant cell/region quarantined and charged.
An explicit transfer may keep a buffer under a bounded provider/cleanup owner,
but that buffer's storage cannot be reassigned while the transferred borrow is
live. New capacity cannot be manufactured by refunding the old owner early.

Prove non-escape or revoke all relevant surviving guest-derived references.
Include capability registers, spills, stacks, TLS, saved signal/exception frames,
host-held copies, callback closures and descendant results. A trusted root's
ability to allocate fresh authority is part of the monitor TCB, not an excuse
to leave old activation authority reachable.

Match revocation to logical allocation domains. Test arena reset, suballocator
reuse, pool-slot recycling and unmap/remap at the same address, including cases
where the parent allocation was never freed. Reinitializing bytes does not
remove references elsewhere; removing references does not initialize old data.
Both obligations need evidence. A software handle generation protects checked
entry, not direct memory access through an old capability.

Bound quarantined bytes, retained metadata, revocation work, scan bandwidth,
retirement delay and active pins. If the bound cannot be met, stop admission or
use the declared failure/recovery policy while retaining outstanding charges.
Do not claim a reusable cell because a revocation request was queued or a
provider future was dropped. Native fault/exception unwinding, register state
and healthy subsequent entry must be qualified together.

## Controlled sharing after basic retirement works

Add one immutable capability-free byte buffer and a second compartment.
Freeze all writers before delegation; a read-only B reference does not revoke
A's writable aliases. Retain a unique allocation owner and bounded borrows;
prevent reuse until every permitted borrower has retired. Wrong sealed types,
stale generations and replayed gate objects must fail through checked entry.

Preserve LSF's opaque payload/result representation, limits and failure/audit
semantics. Native-to-native sharing is a separate experiment from a Wasm
canonical-ABI adapter. It is not proof of zero-copy current local service calls,
permission union, shared transaction authority or general object-graph sharing.

## Independent MPK experiment on current Wasmtime

Begin with an observed cost in the exact current compact pooling baseline.
Compare against an explicitly built/selected MPK candidate with the same guest
work, bounds, fresh Stores, capacity, audit and cleanup. Record upstream default,
feature closure, call-hook behavior, runtime CPU/OS support and actual selected
mode. Do not compare a large-guard generic default only against a warm candidate.

Test host/guest transitions, async suspension/migration, nested callbacks,
signals, faults and key reuse. No old worker context may reopen access to a
different activation; sharing a key cannot be assumed to isolate simultaneously
accessible page groups. For a native MPK design, rights-changing instructions
and syscalls need additional controls; the Wasmtime option does not provide a
native-code admission discipline.

Bind any code/layout/security-affecting option into prepared/native identity.
Missing required hardware must fail closed. An explicitly optional performance
selection may use an observed portable fallback only if it preserves the
requested guarantees, uses a compatible artifact and is allowed by policy.
Never silently replace a required hardware boundary with `local-experimental-v1`.

## Adversarial matrix and observations

Every case requires positive controls, a deliberate violation and source-bound
observations of accesses, host effects and physical retirement. An advertised
feature, compiler flag, hardware signal or successful build is not sufficient.

| Boundary | Required evidence |
| --- | --- |
| Bounds and authority derivation | Out-of-range reads/writes/execute, forged tags, permission expansion and wrong entrypoints cannot access host/neighbor state. Check actual bounds, including unrepresentable subranges and alignment padding. |
| Transitive authority | Inputs containing valid capabilities cannot leak an unintended host object or broaden authority through nested references. Test code, data and default legacy-address roots separately. |
| Gate and OS policy | Wrong sealed type, stale activation/generation and unauthorized host/OS operations fail. A valid object cannot select a different tenant, grant, provider or ledger. A full required audit journal prevents dispatch. |
| Lifetime levels | Test access after free while quarantined and after actual reuse as distinct cases. Strict immediate denial is claimed only when implemented; later activation data must always remain protected. |
| Logical reuse | Retain interior, narrowed, sealed, register and host-held references across arena/slot reset and same-address reallocation. Old authority cannot reach the next activation, including nested-allocator reuse without parent free. |
| Initialization | Reused stack/heap/output cannot reveal prior activation bytes or capability tags. Zeroing alone cannot make stale writable authority safe. |
| Cancellation and late work | A delayed callback/provider/child retains its original owner and region. Dropped waiters do not refund live storage; late completion cannot mutate a new activation. |
| Sharing | Test retained writable aliases, premature reuse and capability-bearing payloads. Read-only borrowing must not be reported as immutability without writer exclusion. |
| Execution and fault recovery | Infinite loops, stack/heap exhaustion, capability faults and abnormal returns obey declared bounds. Observe actual guest stop and a healthy next invocation; a killed harness is a failed inner containment result. |
| Worker protection state | Migration, nested entry, signals and exceptions cannot retain another activation's PKRU/overlay, TLS, stack or return authority. Test key exhaustion and reuse under bounded capacity. |
| Policy currentness | Revoked publications/providers/grants deny new logical starts even with retained hardware handles or code. Memory revocation does not implement policy revocation or erase legitimately copied data. |
| Cleanup pressure | Exhaust arena, quarantine, revocation, metadata and image bounds; interrupt initialization and teardown. No false reuse, leak, unbounded helper growth or per-deployment dormant heap/thread/listener. |

## Measurement, portability and promotion

Keep functional emulator/model results separate from FPGA or silicon timing.
Record ISA/extensions, capability ABI, tag behavior, CPU/bitstream, firmware,
kernel, monitor, compiler/libraries, allocator/revoker and final artifact hashes.
Do not infer performance by comparing different architectures without controlled
baselines, or infer compatibility from a Linux demonstration image.

Measure preparation/load, cold and fresh warm-code activation, checked entry,
compute, copy/share paths, faults, interruption, revocation and full retirement.
Report latency distributions, CPU, code/pointer/metadata footprint, virtual
reservations, committed memory/RSS, peak quarantine and time until actual reuse.
MPK measurements must include its transition/call-hook cost and generated bounds
checks. Compare the same requested guarantees; weaker modes are separate cohorts.
Larger concurrency, profiling and soak campaigns need separate scope.

A promotion ADR must identify the supported workload/platform and exact guarantee,
trusted computing base, artifact/ABI contract, current authorization owners,
fault/time/resource bounds, retirement evidence, maintenance/update ownership
and fail-closed selection/disable behavior. A library study, engine port, native
capsule backend and MPK optimization are different deliverables. None may become
a required dependency or redefine the portable capsule contract by implication.
Retain negative results and raw evidence with their original source identities;
deferral is valid if safe reuse, bounded retirement or a worthwhile benefit cannot
be demonstrated.
