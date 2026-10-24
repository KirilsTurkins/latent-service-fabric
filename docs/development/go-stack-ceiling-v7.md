# Go v7 single-stack ceiling (source only)

The explicitly selected `go-component-activation-v7` adds a fixed 1,048,576-byte
ceiling to each dynamic logical Go stack, including initial/adaptive stacks,
growth and direct GC-forced copies. It inherits v6 Task/QueuedWork and managed
maintenance ownership. The normal default remains `go-component-async-v1`;
v1–v6 derive their original runtime overlays. No new owner, reservation, native
worker, byte counter, result queue, allocation or refund is introduced.

The compiler authenticates the complete original Go1.27.3
[`runtime/stack.go`](https://github.com/golang/go/blob/go1.27.3/src/runtime/stack.go)
(46,093B, SHA256 `0225942ade2eed1e4ec5a0e813c66b3ed06c142c33c987b2fd9e031a0b871d3d`),
then derives exactly three guards. The checked-in source fixture and adjacent
upstream BSD license retain that original. `stackalloc` rejects oversized
requests after the original scheduler-stack/power-of-two checks and before any
pool/cache/span/system allocation. `copystack` checks its full-width `uintptr`
before the GC delta and `uint32` narrowing. `newstack` checks before the original
growth-limit branch. Missing, changed, duplicated or already-derived source
refuses. The private bridge's exact bytes are separately recipe-pinned, so
replacing a captured bridge cannot raise the fixed constant while claiming v7.

Original `runtime/debug.SetMaxStack` implementation and return values remain
unchanged. Its lower growth limit is still checked; a larger requested value
cannot raise the independent v7 ceiling. Original stack layout, GC roots,
pointer adjustment, copying, shrinking, freeing and cache/span ownership are
unchanged. An old stack remains live while its replacement is allocated and
copied. Cached spans and metadata remain in the original Store until its actual
retirement; the ceiling neither refunds nor replaces aggregate memory charging.
Normal projects still default to the original 64MiB activation memory budget,
and source-bound custom finite project limits retain their existing meaning.
This is no independent aggregate stack/heap/GC/native-byte ledger.

The no-concurrency path adds no dynamic structure or per-activation owner beyond
v6. This is still the finite maintained single-threaded Wasm runtime, not native
Go or a multicore guarantee. Unsupported native operations, finalizers and
cleanup callbacks retain their existing refusals. V7 does not enable raw
networking: the existing declared-stream selector remains v5-only. No new
capability or grant is installed.

Normal project creation/capture, dependency selection, compiler staging, runtime
selection receipt and the strict signer's closed profile set all name v7.
The original Go source and derived runtime output digests are recorded by the
existing compiler transformation inventory; captured SDK and recipe inputs
remain bound to their normal signed observation. Installed historical signers
cannot be relabelled v7: actual future qualification needs a signer built from
the new maintained closed-profile source.

Six focused source controls exercise the complete original/inverse derivation,
source/bridge refusal, actual overlay writer routing, incomplete-profile
refusal, normal project/distribution/receipt binding and actual host-parser
environment separation. The host checkpoint parser
is prepared in `Compiler.__init__` before the guest overlay is derived in
`compile`; its original host preparation explicitly clears GOFLAGS to
`-mod=readonly`. The GOROOT compiler copy has only its original scheduler patch;
no v7 stack source is installed there. Only the later guest overlay pairs the
three stack guards with their Wasm-runtime bridge. Existing queue/managed selector controls preserve their old
unknown-profile refusals by testing v8. These controls run no Go compiler or
guest and establish no actual stack-exhaustion result.

The prepared owning programme builds TWO fresh normal v7 components: one
ordinary source with a depth2 initializer, and one closed depth96 initializer
variant. Real module initialization precedes the exported function, so request
mode cannot safely select initialization behavior in one immutable component.
No entropy/timing selector or extra host operation is introduced. Normal project
creation/capture and the actual public Go builder retain each original source,
SDK, WIT, recipe, transformation, component and GoCapsule build observation.
A newly source-matched native harness packages/signs those actual observations
through the strict v7 decoder and normal catalog admission. This is in-process
package/sign/admit, not a released standalone operator CLI qualification.

Exactly seven attempts are required: below-cap recursive stack/GC/checksum;
growth-cap refusal; fresh success; raised SetMaxStack plus cap refusal; fresh
success; initializer-cap refusal; then fresh ordinary success after a normal
deployment change on the SAME backend. A full idle/retirement precedes that
change. Both exact publications are authorized for the same caller/user in the
initial bounded policy, using only existing runtime capabilities. No Store,
initializer or observer is reset or retried. Every actual result must identify
its resolved release/publication, new Store and original owner/quota retirement.

Each actual package, deployment and request selects1billion fuel,64MiB and
120seconds, with zero child/network/state/blob/log/effect allowances. The
existing generic test factory/policy upper fuel ceiling remains10billion;
the normal admitted request supplies the effective Store fuel. This distinction
is recorded explicitly. V7 inherits the ACTUAL v6 baseline
Task16/Executor2/Queue16/Wait4/Timer2/Result2/Native2, including eight prepaid
managed queue owners. The earlier v5 networking programme keeps Queue2 and its
own original limits; neither existing profile is changed to fund this programme.

A read-only, nonexecuted compilation of the exact ordinary recursive function
must retain concrete SP-relative array initialization/copy, non-tail recursion,
frame bytes and absence of array heap escape. The actual emitted component is
independently parsed for that recursive function, a normal self-call and a
post-call array copy; actual live StackInuse/GC growth and checksums must agree.
Reference source or compiler diagnostics alone establish no signed stack result.
All source-only preparation, four new strict protocol/capture controls and the
earlier six production-source controls retain their separate scopes. No old
Go runtime/queue/network campaign is replayed by this owning lane.

Cap refusal attribution is a separate mandatory gate. The private `nosplit` /
`noinline` `runtime.lsfStackLimitExceeded` leaf calls the existing abort primitive
without printing, allocating, importing or trying cleanup on an exhausted
stack. Before executing cap cases, require the actual emitted component's
core-module/function-index/body-range mapping to identify that exact leaf and
its three guard call sites. Numeric collisions with any other emitted core
module are refused. A bounded development-only original Wasmtime numeric-frame
observer then authenticates its presence in the actual failure. Its module
ordinal is FIRST-SEEN IN THE BACKTRACE, never the static module index. The
one-arm observer uses three separately configured factories for three failures;
normal fresh invocations reuse each failure's original backend. Truncation of
older recursive frames is retained honestly; the positive cap leaf itself must
be among the original at-most16 captured frames. Generic
`GuestTrap`, fuel exhaustion, memory exhaustion or an unrecognised frame is not
cap evidence. That observer and concrete mapping must be reviewed before a
campaign; neither is claimed executed by this source slice.

This is partial #742 criterion5 source preparation. Actual compiler, component,
signed runtime/initialization refusal, provenance decoding and retirement
qualification remain pending. It does not complete independent aggregate/native
cost accounting, production provider/kernel requirements or the whole ticket.

First owning attempt: source `3c30f9c0634d60864928085b6630bd638775ad1b`,
[run40078401724](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/40078401724),
failed while compiling the new native harness: Rust E0382 reported that
`consumer` had been moved into `store.apply` before its policy/budget diagnostic
read. Both normal Go component builds and the compile-only stack placement
reference completed, but no signed attempt executed. The original failed run
and artifact12554755854 remain failure evidence. Retaining a deployment clone
for that diagnostic fixes the harness ownership error; runtime qualification
remains pending the same seven-attempt owning programme.
