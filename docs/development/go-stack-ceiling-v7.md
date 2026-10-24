# Go v7 single-stack ceiling (source only)

The explicitly selected `go-component-activation-v7` adds a fixed 1,048,576-byte
ceiling to each dynamic logical Go stack, including initial/adaptive stacks,
growth and direct GC-forced copies. It inherits v6 Task/QueuedWork and managed
maintenance ownership. The normal default remains `go-component-async-v1`;
v1 through v6 derive their original runtime overlays. No new owner, reservation, native
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

The second owning attempt, source `7fdc0ced18a7e1c71ff16836ab52a92489ec49e6`
([run40079647085](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/40079647085)),
compiled the native harness but normal packaging rejected the first manifest
before admission or guest execution: the fixture tenant `tenant-a` disagreed
with its `tests:caller` world/export namespace. The corrected closed programme
uses tenant `tests` consistently in the captured project, signing/admission,
and its explicit native fixture identities. Original shared fixture defaults
remain `tenant-a`; package namespace validation remains unchanged. Artifact
12555111269 and its failed result remain history. No runtime case is credited
from either failed attempt.

The third attempt, source `67b233b1bafdf44943499b19b42d536b837e8f75`
([run40080836178](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/40080836178)),
passed normal package construction, then the strict GoCapsule observation decoder
refused `MalformedProvenance`: builds selected no packager, so their observation
correctly lacked its mandatory `packager` material. No signed attempt executed.
Artifact12554499179 remains failed history. The corrected owning driver freshly
builds both normal packaging CLI products from the current source, runs real
package and inspect commands for both Go builds, and requires completed normal
package output. It preserves the strict decoder and all existing caps. The
native fixture checks that every original CLI content layer is unchanged when
it adds its existing policy-required embedded SBOM through the normal library;
only the generated package-input receipt and added SBOM differ. Signing/admission
remains an in-process test operation, not released standalone operator delivery.

The fourth attempt, source `45710aab2d31dbbd8c7171717223cc5b373b48fd`
([run40082039137](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/40082039137)),
completed both normal CLI package builds/inspection and strict observation
decoding, then the unique-module mapper refused the expected recursion symbol.
The actual Go name section spells it
`wit_component_export_tests_caller_api.stackFrame`; the source-only expectation
had used a slash instead of the emitted underscore. All four other required
runtime symbols were present. The correction binds that exact emitted literal
in the mapper and strict reader, with no normalization or fallback. Artifact
12555289147 and the failed result remain history; no signed runtime attempt
executed. The unique-module, guard-call, body-range and cap-frame predicates
remain mandatory.

The fifth attempt, source `27c4e194ccef6df2ed3201f6b473bd2217a99431`
([run40083012315](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/40083012315)),
proved both actual emitted module mappings, their three cap calls and ordinary
recursive stack/copy structure, then failed before a request when the shared
fixture tried to deploy its unused second-publication role as service `callee`.
Both normal packages deliberately declare service `caller` for the later
caller-publication change. The closed Go-only fixture now asserts both actual
manifest service names, zero child-call budgets and absence of service-invocation
imports, then deploys only the real caller. Other fixture constructors keep
their normal callee deployment validation. The existing inert callee scope and
binding metadata grant no extra lifecycle credit: no callee is deployed or
invoked, and both real publications still pass ordinary admission. The later
caller repoint remains an ordinary validated deployment update. Artifact
12555674832 and the failed result remain history; no signed request executed.
