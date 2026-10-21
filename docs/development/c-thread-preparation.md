# Selected C context preparation

This source packet adds `c-context144-sync-cooperative-v1`. It has no hosted
execution result yet and does not complete #744. The default C project and the
existing Rust context40 profile keep their selection and serialized settings.

The C project must explicitly name `threadingProfile`. The normal captured C
builder owns the four runtime files, the two runtime WIT imports, linked-libc
mode, guarded stack layout, derivation and ordinary component encoder. The
existing `capsule_contracts` executable performs the two bounded derive/bind
operations. Its original two-argument WIT operation is unchanged. Static
archives are refused by this first profile. The selected package declares
`cooperative`; this declaration provides no Task, Native or activation grant.

The final component has one top-level `latent-c-original-core-v1` custom
section. Its closed versioned envelope contains the original linked core and
the public export identity, at most 1 MiB together. Duplicates, unknown versions,
trailing bytes, invalid names and non-core preimages are refused. Nested
sections are not selected. The complete component still has the existing
8 MiB verifier bound. All bytes, including this original preimage, follow the
ordinary component digest, package signature, AOT input and cache identity.
There is no asset reader or out-of-band original-core channel.

The ordinary node operator independently selects
`engine.threadingProfile: "c-context144-sync-cooperative-v1"` and
`providers.activationRuntime.nativeThreads: true`. The latter installs the
existing Native start provider on the same activation broker, identity and
finite limits; it creates no second executor or owner quota. The normal
protected configuration, audit and capability-policy prerequisites remain.
An explicit `latent:runtime-native/threads@0.1.0` binding and independent grant
are still required. Scalar or activation aliases do not install this binding.
Every JIT compilation, native loading and compiler-worker route recomputes the
complete C derivation and final graph. The immutable proof and prepared
descriptor must agree on both the C profile and whole-component digest before
reuse or instantiation. Proof data alone selects nothing. A C proof cannot be
replayed as Rust or as default preparation.

The fixed root wrapper retains the original canonical result in Wasm locals.
After the actual C finish function and TLS destructors return, it checks the
root SP/frame state, marks the record's frames exited, and settles only the
root record's logical Native and Task tokens through the exact typed settle
import. Absent lazy tokens must be an all-zero pair; a malformed pair or
non-Ok host result traps. Detach follows both settlements and has no following
C or host calls. The host's existing finalization guard remains strict, and
its separate physical stack/metadata owners survive until Store destruction.

The installed C recipe stages the optional helper and the four exact runtime
sources in its normal inventory. `tools/c_capsule.py new ... --threading-profile
c-context144-sync-cooperative-v1` captures those sources into the project's
existing SDK lock. The installed `tools/dev_guest_recipe.py` uses the same
normal selected builder and its existing `capsule-contracts` executable. This
is source wiring and an installed source-control result, not an installed guest
execution qualification. Omitted and explicit single-threaded creation still
produce identical ordinary projects without extra runtime assets. Selected
recipe/source changes receive a new identity; no new source is omitted to
preserve an old cache fingerprint.

`engine.activationStackAccounting: "activation-owned-v1"` separately selects
the existing root-only native stack owner for ordinary activation profiles.
It requires the existing activation-runtime installation, keeps native threads
disabled, and uses the original activation byte budget and physical owner.
It adds no provider, capability, quota, proof requirement or guest import.
Omission retains the old engine-managed stack selection. C threading implies
activation-owned stacks. The normal check report includes these selected
facts; default report fields remain absent. The new ordinary-stack source
controls are unrun Rust cases until the reviewed hosted producer executes them.

## Prepaid verification work

The original component and verifier work are two costs. Borrowing the original
core from its envelope saves one copy but does not pay for recomputation.
`C_VERIFICATION_WORK_BYTES` is exactly
`16 * 2 MiB + 8 MiB + 8 MiB = 48 MiB`, a conservative allowance for owned input
representations. It is not a process RSS assertion or a replacement allocator.

| Verification phase | Simultaneously covered owners | Reserved allowance |
| --- | --- | --- |
| Finite preflight | Borrowed source; bounded parser/control storage; one malformed reader's transient typed/element containers before refusal | Within the full 48 MiB already admitted |
| Recomputed derivation | Renamed, template, contextual/child and rooted byte images; current encoder capacity; old/new section/body/data snapshots; template encoding/image; final ABI output/clone | 16 byte-image units of 2 MiB, including encoder growth and nonoverlapping snapshots: 32 MiB |
| Recomputed derivation | Bounded numeric signature and function/global arrays, export maps, call graph/closure/pending vectors, snapshot headers and names | 8 MiB |
| Recomputed derivation | Pinned validator numeric type/function state, operand/control stacks and local maps | 8 MiB |
| Final graph | Recomputed expected core and copied source/encoded section arrays; four bounded core descriptions; inline export/argument maps, aliases, canonical options and public/private component types; at most one current typed reader | Within the same 48 MiB; derivation intermediates and validators have dropped before graph construction |

The bound is valid only for the enforced finite encoding. Before the first full
Validator or reencoder, the C preflight checks numeric core type encodings
directly, at most 160 types with 32 scalar values each, 256 original functions
(280 after derivation), 256 globals with exact numeric constant initializers,
4,096 aggregate locals, 16,384 original operators (32,768 derived), control
depth 256, branch tables of at most 256 labels, bounded import/export names,
256 data/element groups and 256 entries per function-index element group.
Data/element offsets are raw exact `i32.const` expressions. Eight ordinary
funcref tables and eight memories are the finite table/descriptor limits;
reference-expression elements and table initializers are refused before typed
decoding. Typed-select, exception, core continuation/stack-switching, SIMD,
atomic and GC operation prefixes are refused before allocation-bearing typed
operator decoding. Branch-table labels are bounded before their typed skip.
TLS image extent is at most 128 KiB. The checked expression
`original bytes + TLS extent + 16 * original operators + 128 KiB` must fit
2 MiB before any recomputed image is allocated.

The final graph has four cores of at most 2 MiB, at most 32 core instances and
32 component instances, 512 aliases, 256 canonical functions and 4,096 parser
rows. Top-level structural sections are at most 64 KiB; typed sections are at
most 16 KiB. A conservative count of the recursive component/instance/module
type prefix bytes is at most 16 before recursive type decoding. Coincident
string/index bytes count too and can refuse a wider encoding; they cannot
underestimate actual nesting. Nested executable components are refused.
These are supported-profile restrictions, not increases to guest/runtime limits.

`PreparedCache::begin_with_verification` checks **original source + 48 MiB**
against the unchanged existing per-preparation source allowance, before a
worker/fetch/verification starts. The existing affine `PrepareReservation`
keeps both costs in `preparing_source_bytes` through cancellation/unwind and
synchronous verification. Publication transfers only original source bytes to
resident accounting and releases work after all verifier temporaries dropped.
Cache rekeying transfers the same reservation. Queue/coalescing routes retain
the same owner; they do not create a second work quota.

`IsolatedAotCompiler::reserve_selected` similarly adds 48 MiB to the existing
aggregate input-byte reservation before reading a selected C component. Its
`WorkPermit` outlives input storage, parent verification, child execution and
reap. The worker receives the closed trusted C bootstrap profile and checks
the same proof under that parent's retained allowance. The original protocol
component-size limit, sandbox, document and native-output limits are unchanged.
Native loading also retains its ordinary cache preparation reservation.

If either unchanged allowance cannot admit source plus work, preparation
refuses before recomputation. Rust/default preparations add zero bytes. At the
existing defaults, an at-most-8-MiB C component requires at most 56 MiB from a
64-MiB cache preparation allowance and from the AOT aggregate input allowance.
The AOT aggregate still independently limits simultaneous jobs; no cap is raised.

## Required next actual programme

The next reviewed owning lane must build one ordinary captured C guest through
this selected normal builder and execute real pthread/C11 create, self/equal,
join and independently scheduled child callbacks with thread-local values and
the original libc errno. It must observe a genuine pending join/Wait and the
original native admission/physical owner events, not infer them from a thread
handle or a successful root result. Cancellation, root trap, exact invalid
identity/join states, Store retirement and fresh invocation remain mandatory.
The earlier 889 graph/ABI result is historical source evidence; it is not this
host profile's runtime result. Mutex/condition variables, CPU checkpoints,
preemption, arbitrary C++ dynamic TLS, shared-memory atomics and broad library
compatibility remain outside this finite slice.


## Authenticated native producer observation

[Run 39581446809](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/39581446809),
job 119159766073, compiled the five normal managed-guest native products from
`f0d36b38d39a837cef7f6242b4b4a99aa36b8b75`. Its complete 73-member archive,
3324 native source files, 134 auxiliary inputs including generated-protocol
sources, all five binary identities and 33 bounded ordered commands were checked.
The original 50 Rust and 15 Python controls passed alongside 55 transformer and 11
selected cache/engine/operator controls. The compact
[producer observation](../testing/evidence/c-thread-native-2026-10-21.json)
keeps signed guest qualification and C lifecycle qualification false.

The immutable `tools/c_thread_native_products.py` reader retains that exact
source/run/job/archive/receipt tuple; earlier native readers remain unchanged.
The shared reader admits at most 64 fixed stage names, still requires their exact
order and successful outcomes, and retains the original 1320-second aggregate.
The source composition adds no native input difference from the exercised f0
source. No C guest was compiled or admitted by this producer.

Earlier owning failures are retained: 5aae failed digest formatting,789ec failed
a test-only runtime-limit initializer, de637 failed missing test encoder imports,
and 382 compiled all 55 but exposed over-aligned byte operations in the new C
root wrapper plus a malformed negative fixture. The corrected byte operations
retain offset 80, typed logical token retirement and all original quotas; the
negative fixture still requires refusal before allocating opcode decoding.
None of these failed runs supplies passing qualification credit.


The first ordinary C owning [run 39586182661](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/39586182661)
failed during linking: the original libc and the selected source PAL both defined
`pthread_setspecific`. No component or guest result was produced. The selected
compiler now gives exactly the four pthread key and four C11 TSS entry points a
private source-PAL namespace across ordinary declarations, application calls and
PAL definitions. Its generation-checked keys stay in the charged TLS context;
libc retains its original internal keys and TLS `errno`. Static archives remain
unsupported by this first profile. No multiple-definition allowance is used.
[The retained failure and preprocessing control](../testing/evidence/c-thread-runtime-link-failure-2026-10-21.json)
provide source evidence only; all seventeen runtime cases remain required.

A separate actual development formatter failure is repaired with the pinned
Rust 1.97.1 formatter, each Cargo package edition and the repository configuration. The
[closed formatting comparison](../testing/evidence/c-thread-native-rustfmt-2026-10-21.json)
binds the exact original and formatted hashes of two C transformer files, with the other
3322 native files unchanged. The consumer admits only the two complete frozen
source inventories for that historical comparison; f0 remains the original
compiled source. This comparison does not claim that the formatted tree was compiled.

The next ordinary C campaign uses the separate
[c713 native tuple](../testing/evidence/activation-stack-native-2026-10-21.json).
Its 132 Rust and 16 Python controls passed, including the complete sixty-case C
proof suite, eleven exact C profile controls and eleven ordinary-worker controls.
The shared source guard accepts only that exact native tree, the pinned reversible
`install_stack_accounting` helper extraction, or that extraction plus two exact
explicit enum defaults in the existing engine test. It records the compiled and
current identities separately; the other 3324 or 3323 native files remain byte exact.
All seventeen signed C lifecycle outcomes still require actual guest execution.


The c713-backed [ordinary C attempt](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/39606172348)
passed linking, full derivation, final proof binding, validation and contract
generation, then stopped at compatibility inspection: the base V5 manifest does
not recognize the selected native-thread internal port. No guest ran. The
proposed selected C supplement preserves that original inspection and base ABI,
binds the exact port WIT and full original-core proof, and requires the existing
native verifier to reproduce the final component bytes. It is compiler evidence;
independent runtime validation, Native authority and all seventeen guest outcomes
remain required.
