# Rust standard runtime source port

This infrastructure source experiment implements the `std::time` platform
clock calls beneath ordinary `Instant::now` and `SystemTime::now`. It replaces
the pinned Rust 1.97.1 unsupported time selector with an LSF clock PAL for
`wasm32-unknown-unknown`. It preserves the upstream time representation,
checked arithmetic and epoch limits, and uses the exact synchronous canonical
clock imports. It creates no executor, task, timer, native thread or OS clock.

`tools/rust_standard_clock_profile.py` authenticates the official source archive,
retains the exact reviewed originals and emits a separate overlay and source
receipt. The checked-in original preimages come from Rust commit
`8bab26f4f68e0e26f0bb7960be334d5b520ea452` under MIT OR Apache-2.0; their hashes
are pinned in the helper. This source stage never alters an installed compiler
or sysroot. Application code does not inject an LSF executor or runtime patch.
The exact upstream [MIT](upstream/LICENSE-MIT) and
[Apache-2.0](upstream/LICENSE-APACHE) texts accompany the original preimages;
LSF overlays do not replace their attribution.

The profile is **unqualified source**, with no automatic builder selection yet.
It needs a rebuilt authenticated sysroot, owned clock-world component metadata
and genuine signed ordinary Rust component evidence before the maintained
builder may select it. `no_std`/`alloc` sources remain unchanged. Networking
authority is separate.

Logical threads, TLS isolation, synchronization/channel parking, sleep/timers,
default executors/reactors and compiler checkpoints still require real ports.
The original failed thread creation and sleep behavior remains intact; the
single-thread `Cell` mutex is preserved and never described as concurrent.
No signed component or default Tokio/Rayon compatibility is claimed.

The next source slice in `tls.rs` selects the unchanged pinned key-based std
TLS storage beneath ordinary `thread_local!`, including its alignment,
initializers, recursive initialization and destructor sentinel rules. The
backend uses canonical per-thread context slot 1; wit-bindgen's slot 0 stays
owned by its original implementation. Each lazily admitted context/key entry
holds an original activation Native owner, while its guest bytes retain the
original linear-memory limit. An accepted thread prepares its context with
the existing task continuation before start; closure does not authorize new
independent work. Physical entries/contexts free before settlement. Bounded
destructor cycles, destroying sentinels and nested retirement stay fail closed.

`tools/rust_standard_tls_profile.py` preserves the exact official std originals
and stages only the target selector and TLS backend. The canonical register
and settle layouts come from an actual pinned wit-bindgen 0.62.0 generation;
`activation-abi.json` binds that public source observation to the original WIT.
No installed sysroot or thread implementation is selected by this source stage.
The runtime provider/grant, owned thread/export lifecycle, shadow-stack
save/restore on every suspension, engine resource admission and actual signed
std/thread/TLS proof are required before selection. Canonical thread primitives
alone do not establish those requirements or safe compiler preemption.

`tests/clock_native.rs` exercises this actual PAL source using explicit fake
host clock imports. Run that native reference harness with one test thread;
its evidence does not qualify a guest sysroot, component or runtime.

Run each `tests/tls_native.rs` reference case in its own native process with
one test thread and an aggregate bounded deadline. The deliberately retained
destructor-cycle/sentinel cases assert that owners remain charged on failure;
they are not reset, retried or reported as successful runtime retirement. The
native allocator trace delegates to the real `System` allocator and records
ordering, not guest allocator/RSS measurements or scheduling qualification.

## Owned std build and ordinary clock control

`tools/rust_standard_sysroot_build.py` now executes the clock-only overlay's
actual locked offline std build. The official authenticated source archive also
contains its vendor closure. The build owns a fresh source/target directory,
records the compiler distribution and each emitted library, and never changes
the installed compiler. Only libraries named by the successful Cargo artifact
graph are installed in the output: earlier failed-build libraries cannot enter
the new sysroot through a cache glob. The required
`-Zforce-unstable-if-unmarked` compiler flag preserves std's internal stability
checks on its dependency graph. TLS and thread overlays are not selected by this
clock-only build.

## Standard stdio profile

The owned clock/sysroot build now selects a pinned stdio PAL alongside clocks.
Its default PAL returns `io::ErrorKind::Unsupported` for nonempty stdin reads,
stdout/stderr writes and flush. Empty writes can complete with zero bytes. The
outer std wrapper no longer masks these errors as bad-file-descriptor success,
and this target's stdout buffer has zero capacity, so an ordinary buffered
`print!` cannot acknowledge bytes that will later be discarded.

The separately selected `rust-standard-logging-v1` authoring profile uses
`stdio_logging.rs` beneath unchanged `std::io`, `print!` and `eprint!` calls.
The compiler-owned `latent-standard-stdio` crate supplies one fixed intra-core
Rust-ABI symbol using the SDK's actual generated typed LOG binding; it registers
no application callback. Both sides require the same pinned compiler. Standard
output maps to info and standard error to error, with no guest-supplied identity
fields. Each synchronous call accepts at most 256 UTF-8 bytes and 16 vectors;
vectors are joined before decoding. Separate incomplete UTF-8 writes fail
explicitly. A false provider result, invalid field, unavailable provider, budget
exhaustion or reentrancy remains an error. No retry or hidden worker is added.
Flush has no buffered work and acknowledges only completed sink acceptance,
never remote delivery. Drop and failed panic reporting perform no hidden log.

`rust-standard-closed-v1` selects the same owned build with the concrete closed
stdio PAL. These explicit profiles require `build --standard-runtime` with the
current recipe/compiler/source/rlib-bound build receipt. Target-only Cargo
configuration leaves host build scripts and macros on their original sysroot;
captured builds mount the owned target sysroot read-only and retain its identity
in build materials. A prepared build receipt is a builder assertion, not a
publisher signature or an authorization. Declaring LOG installs no provider or
grant. The legacy stock profile still uses the unmodified prebuilt standard
library; no supported logging or concrete-Unsupported stdio claim is made for
that separate profile.

The eight host tests in `stdio_reference.rs` exercise the actual PAL files with
a synthetic bridge. `tools/run_rust_stdio_reference.py` also extracts the three
exact pinned upstream methods: the old write/write_all/flush Unsupported
assertions fail and the new reference passes. These controls do not qualify the
rebuilt std, generated binding, component or signed node. The later signed
observation below supplies the finite component evidence separately.

The new `Rebuilt Rust standard stdio and signed ordinary libraries` job is an
independent 20-minute child of the existing authoring job. It reuses only that
run's exact native five-product tuple and four original companion builds, then
builds closed and logging std from the authenticated Rust source archive. A
normal captured outside library calls only ordinary std APIs and a transitive
`include_str!` resource; original outside sources are removed before offline
component compilation. The existing signed runner retains all 27 original
outcomes and adds three closed-error/fresh calls, or two pre-admission denials
and fourteen logging/error/failure/fresh calls. Each new completed/fault call
requires process reaping and the original idle accounting samples. No original
job command, limit, signing rule or runtime budget is relaxed.

The first branch-native campaign at
[`c0814dbb`](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/39287224120/job/118189609658)
built both owned standard libraries. The closed profile compiled, signed and
completed all 30 required node outcomes with component
`sha256:573125eb56798d9f26a37800ca4989dacf1d7e21b81ca069a861ca549821baae`.
The logging application then failed compilation because its app-world macro
lacked the declared LOG interface mapping. Creators now reuse
`latent_guest::bindings::log`, preserving existing mappings and template bodies.
The normal compiler recipe excludes workspace Cargo metadata; explicitly prepared
standard-runtime profiles still capture and authenticate it. These corrections
required a fresh campaign. The later
[6ffab campaign](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/39293312298/job/118210886706)
passed closed30 and logging43 with authenticated owned std, unchanged ordinary
library calls, all73 known/reaped outcomes and both clean shutdowns. All seven
jobs in that workflow passed. The historical compiler/helper ancestry remains
separate from the fixture source; later import/IDE repairs did not change the
exercised stdio implementation. This finite observation does not qualify all
APIs, concurrent logging callbacks or remote delivery.

`tools/qualify_rust_standard_clock.py` prepares an ordinary `SystemTime::now`
component using that emitted std graph and the pinned bindings/component tool.
Application code calls no SDK clock or executor. Its optional, explicitly hashed
`clock_admission` test executes this actual component through the production
broker, using the existing test fixture's cryptographic publisher/builder,
current grants, two fresh Stores, revocation and physical cleanup. The driver
captures the source, lock, tools, sysroot and actual component surface, and
retains failed attempts separately. Native policy/trust work stays on the
ordinary Linux temporary filesystem even when receipts are mounted elsewhere.

The maintained `Rebuilt Rust standard clocks and signed grants` job executes
both ordinary `SystemTime` and `Instant` controls through
`tools/qualify_rust_standard_clocks.py`. It authenticates the fixed official
Rust source archive, selects the exact signed clock harness from a successful
current Cargo artifact inventory, and runs separate locked offline sysroot and
component builds. Each component imports its own exact clock interface; each
case requires two fresh Stores, original-budget accounting, policy revocation
and complete sampled owner retirement. Bounded receipts retain component and
sysroot identities, command outcomes, fuel, peak Wasm memory and elapsed time.
This job's execution result is required evidence; adding the job does not itself
qualify a source revision. Its signed test publisher/builder does not establish
production builder authorization. Installed target selection, logical threads,
default executors and native-fiber retirement remain separate requirements.

For example, with the authenticated archive and tool executables already
provided by the maintainer:

```bash
python tools/qualify_rust_standard_clock.py \
  --source-archive /owned/rust-src-1.97.1.tar.xz \
  --rust-bin /owned/rust-1.97.1/bin \
  --wasm-tools /owned/wasm-tools \
  --clock-admission-test /owned/clock_admission \
  --clock-admission-test-sha256 sha256:<reviewed-executable-digest> \
  --output /owned/fresh-clock-attempt
```

This is a finite ordinary clock/component control. Its test signers do not
establish production builder trust, a distributed supported sysroot, default
builder selection or full #743/#689/#683 qualification. Logical threads,
per-canonical-thread native-stack admission, actual fiber retirement,
synchronization, timers, default executors/reactors, safe CPU-loop checkpoints
and unchanged HTTP-client execution remain separate unfinished requirements.

The separate `WasmtimeConfig::owned_native_stacks` profile admits one root
native stack through the original activation's Native ceiling and host-memory
ledger before the Store receives its fuel counter. It requires Linux x86_64,
on-demand allocation and explicit activation runtime limits. A poll-scoped
allocation context follows the invocation across executor threads. The host
allocates zero-filled guarded pages and retains the original reservation until
the actual `StackMemory` destructor successfully unmaps them. Unproven release
keeps the reservation charged and quarantines the execution cell. Additional
stack allocations fail before mapping; canonical thread creation remains closed
because its suspended metadata needs separate pre-start admission.

`tools/qualify_owned_native_stacks.py` reuses the exact current clock harness and
already qualified clock components. Its signed cases repeat the fresh Store
and revocation controls under this explicit profile. Native unit controls also
hold a real Wasmtime call pending, cancel it, and require physical stack release
before the original lease is reusable. The maintained clock job runs both
gates. Native execution is required before this source can be called qualified;
this foundation does not implement ordinary Rust threads, synchronization,
timers, reactors or default executors.

The separate staged native-thread profile reserves original Native and potential
stack capacity before every accepted start. Wasmtime 48 reuses worker fibers and
stacks across logical children, so this finite profile bounds total starts per
activation. A cached worker does not refund an unused reservation. Logical joins
and guest completion flags release no native capacity; unused reservations remain
charged until the actual Store destructor has completed. Actual mapped stacks
still retain their original lease through successful host unmapping. Unproven
physical release quarantines the cell.

Each accepted native child also requires a distinct original Task token. A
bounded host table records consumed tokens through Store destruction, including
after a mapping has actually retired. Copying a token or resetting a guest
context flag cannot bypass Task admission. Table capacity is charged before its
allocation under the same original host-memory budget.

The explicitly selected `owned_native_threads` profile recognizes the separately
authorized V6 support start operation and requires the guarded-stack profile and
original activation limits. It grants no authority; CURRENT stays V5 and frozen
activation WIT is unchanged. Only this explicit profile enables canonical thread
creation, and every executable component must first pass the shared final-byte
sole-consumer verifier. The ordinary Rust thread, futex and executor ports
remain required; this finite host mechanism is separate from those ports.

The staged post-link source transform now routes every linked-core call,
function reference, export and table/global initializer reference to raw
canonical creation through one exact stackless admission body. It validates
the prepared context, original Task token, canonical result and one-shot start
guard before invoking the actual primitive. The original ledger checks the
Task's live kind and admits Native support under the same registration lock.
No guest flag releases the resulting host reservation.

The separate root transform requires the linker's exact immutable
`__stack_low` and initial `__stack_pointer` range. It installs an admitted
Task/Native TLS context before the original Rust body, preserves numeric flat
return values, runs TLS cleanup on that live context, and detaches only after
the last translated frame. A final System-only postlude frees the logical
context before settling its owners. Bootstrap/reaper stack helpers accept the
original stack only while the lifecycle permits it and canonical context is
empty; active children retain their own checked stack. This logical cleanup
does not refund physical Wasmtime stack capacity.

The staged TLS/root lifecycle supports a compiler-owned lazy drain registry.
Pending accepted work prevents root TLS cleanup and owner settlement. Root
destructors and final std cleanup re-enter that drainer before entries retire;
the final detached System reaper releases registry bytes before its context and
Task leases settle. The ordinary thread PAL must install and implement this
registry; the hook and its 23 native source-reference controls alone do not
establish ordinary thread execution or accepted-work drain qualification.

The encoded-Wasm transform controls and separately executed native TLS source
reference cases exercise these source mechanisms. They do not establish a
rebuilt thread sysroot, accepted-work drain,
the std thread/futex API or actual signed child execution. Those requirements
remain open. The internal V2
context prefix is recorded in [thread-abi.json](thread-abi.json); CURRENT V5 and
the frozen activation interface remain unchanged.

The core transform uses `wasm-encoder` and `wasmparser` version 0.259.0.
Component assembly uses the separately pinned `wasm-tools` version 1.254.0,
whose encoded producer is `wit-component` version 0.254.0. A small explicit
WAT module-graph campaign uses that normal assembly and authenticates the actual
final main/private-thunk/fixup graph. It recomputes the fixed admission body,
requires the real imported Native start provider and a bounded original callback
table, and rejects raw-function lifts, mutable-table escape, duplicate creation,
parallel spawn, extra executable modules, dynamic code, repeated main/fixup
instances, guest admission substitutes and early component start. Normal nested
WIT interface export wrappers remain supported.

`tools/qualify_rust_thread_routing.py` runs two normally encoded positive
components and fifteen rejection controls within 180 seconds and 2 MiB of total
command output. Every changed component must pass the actual encoder's Wasm
validator before its verifier rejection can count as a control. Source and tool
identities are rechecked after the campaign, and failures retain a bounded
receipt. The maintained Rust clock job runs this additional campaign without
removing its previous sysroot, signed clock or physical stack controls.

This is a source-routing proof over transparent WAT controls, rather than a
rebuilt ordinary Rust thread program. The verifier emits no permission or
supported-profile claim. The explicit host profile consumes the same verifier
before ordinary `Component::new`, isolated-worker precompilation and native AOT
loading, including the sole authenticated native loader. Its closed compiler
bootstrap rejects unknown profile versions before allocating an Engine. A shared
factory Engine can exist before any component is known; no component is compiled,
loaded or instantiated until its final bytes are authenticated. The immutable
digest proof stays with `InstancePre`, is charged as retained metadata, and is
checked against the exact descriptor and selected profile on prepared-cache,
readiness, activation-start and immediate instantiation boundaries. Profile,
context ABI, one-Task-start policy and V6 interface identity enter ordinary and
native compatibility keys; default V5 identities retain their previous fields.

`tools/qualify_owned_native_threads.py` prepares a separate transparent WAT
mechanism fixture through the normal pinned encoder and the fixed transforms.
Its maintained signed node case exercises a real canonical child, per-context
stack accesses, the original protected Task/Native imports, fresh Stores and
prepared-cache reuse. It also requires child trap/fuel cleanup, copied-token and
total-start quota denial, wrong-kind denial, unstarted accepted work rejection,
a missing grant denied at binding publication before factory or Store creation,
and two correctly encoded but unauthenticated component rejections before
signing. Descriptive package inspection
opens threading syntax only after the same final-byte proof; it installs no
provider and changes no execution profile. All cases retain the existing finite 4 MiB
grant; the explicitly selected mechanism uses 256 KiB native stacks and three
Task/two Native slots. Actual native execution is required before claiming this
gate passed. This fixture executes no Rust/std source and establishes no ordinary
thread, TLS, mutex, condition variable or executor compatibility.

The [2026-10-16 mechanism evidence](../../docs/testing/evidence/rust-owned-canonical-children-2026-10-16.json)
binds the 48 recipe inputs to revision `21e24c85`, the actual native test binary,
three encoded components and nine signed executions. All sampled original owners
retired in each execution; 119 focused native controls also passed. Hosted CI and
the ordinary Rust standard-library port remain separate requirements.
