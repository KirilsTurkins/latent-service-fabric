# Canonical async JoinState backing

The selected Wasmtime native-memory path now admits the complete shared
JoinState cell before publishing either of its two private owners. This is a
bounded accounting improvement for canonical asynchronous calls; the full #745
cost model remains open.

The focused qualification at source `7e6cad7a1f9399f44a019425d8533452f6ba75c4`
passed [run 40179265940](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/40179265940).
Its [machine receipt](../testing/canonical-async-join-state-evidence.json)
binds the original archive, all 27 retained members, twelve successful commands,
six raw test observations, source inventories, tool and executable identities.
The two locked host targets took 75.25435s and 181.658449s to build. Each of the five
private controls and the one actual canonical control executed and passed;
none received ignored-skip credit. No signed JavaScript or SDK/engine/kernel
programme was run by this owner.

## Ownership and compatibility

The selected cell reserves its complete checked Arc header, payload and alignment
through the existing NativeMemory factory before Arc allocation. The actual
compiled layout in this qualification is 80 bytes. This is an assertion witness
for that cell, not a complete allocator/RSS measurement or a new budget input.
The normal host callback-box path and its original metadata owners remain separate.

Both private strong wrappers use Arc::into_inner. Under the pinned Rust 1.97.1
implementation, the last winner obtains the payload after the shared backing and
implicit weak header are deallocated. It then destroys state and wakers before
refunding the original allocation owner. A state-destructor unwind retains the
uncertain charge. No Weak/raw/public Arc alias or factory lifetime cycle is added.

The implementation controls exercise normal completion, cancellation, both final
owner orders, concurrent final drops, confirmation unwind and a waker-destructor
unwind. The real NativeMemoryBinding subcase retires its separately admitted
factory/header owner while the cell remains charged through its final alias.
These private callback observations are implementation witnesses, not a substitute
for the original activation ledger exercised by the canonical control.

NativeMemory=None retains its original Arc<TryMutex<JoinState>> backing and
operation semantics. The private handle enum can enlarge inline handle/future
metadata; existing concrete future-box admission charges its actual Layout.
The v10 source closure preserves all 250 immutable upstream identities and binds
all 259 maintained files and the complete reconstructable patch. Historical v9
product readers remain historical evidence and do not certify this new host.

## Actual original-budget refusal and reuse

The native control compiles its tiny source-owned component with maintained
wasm-encoder/wasmparser, creates the Store/instance and resolves the typed export
before arming contention. Its closed scalar callback path makes the existing
paid HostFuture box request first and the new JoinState request second, before
the application closure or its future is polled. The control reserves the
remaining original memory and requires that second admission to fail with the
original typed ResourceExhausted/memory-bytes cause. The exact request order,
compiled layout and unentered closure jointly identify the cell; size alone is
not treated as allocation identity.

The failed Store is physically destroyed before contention is released. The
control asserts zero original host memory/outstanding reservations, then creates
a fresh Store using the SAME ActivationBudget and remaining CPU allowance. Its
real asynchronous callback returns 42, and physical teardown must again return
the original reservations to zero. These are exercised assertions in the passing
control; the receipt does not invent separately emitted counter samples.

The original activation request remains 1,000,000,000 fuel, 64 MiB and 120s. The owning
job keeps 45 minutes and one 2400s aggregate, with 900s build, 60s case and 30s listing
caps. A 5s cleanup reserve is included inside those limits. Root and vendor locks
remain distinct; compilation reuse is not assumed.

## History and remaining boundaries

The first source `edab1f0ae3315b84b3cf0c1d3ee8bf36032c5d4b` failed vendor-libtest
compilation with 26 diagnostics before any control executed. The correction added
Box/ToString imports only in the test module and enabled cache,threads,coredump
only for the standalone vendor test binary, as required by existing vendor tests.
The ordinary production/root flags and all budgets stayed unchanged. The failed
observation remains failed; the later six-control success is separate evidence.

This slice does not cover remaining scheduler allocations, opaque host futures,
engine GC/cache allocations, complete native heap/RSS costs or networking. It does
not complete #745 AC5 or the whole issue. The source-qualified input tree remains
identified by 7e6c; these separate evidence documents do not relabel it as a new
execution or change the conditional preparation text in its frozen vendorREADME.
