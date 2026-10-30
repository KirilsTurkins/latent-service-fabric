# Owned Rust thread source checkpoint

This is implementation source for the explicit cooperative
`lsf-rust-std-owned-thread-runtime-v1` profile. It is not selected by a shipping
application runtime, and no signed ordinary `std::thread` or ThreadPool result
is claimed. The normal builder recognizes the explicit source profile and
refuses application compilation while its private component graph is
unqualified. The existing clock, logging, entropy, `no_std`/`alloc` and explicit
async profiles retain their separate execution evidence.

The selected target is Rust 1.97.1, commit
`8bab26f4f68e0e26f0bb7960be334d5b520ea452`,
`wasm32-unknown-unknown`, without shared memory or the `atomics` feature.
`tools/rust_standard_thread_profile.py` checks original std selector and Packet
preimages, preserves all other target branches, and composes activation-local
TLS, actual canonical child creation, logical identity, join/detach,
mutex/condition/channel waits, Parker, Once, RwLock and bounded timer waits.
The original ThreadInit, `rust_start`, Packet destructor and result consumption
remain unchanged apart from the selected Packet's final logical Result owner.

The runtime admits each original Task, Native, Result, Wait, Timer, Executor and
queue owner before the corresponding work or infrastructure publication.
System backing stays owned through its actual destructor and deallocation.
User values and the original mpsc/Arc allocations remain paid by the original
Wasm linear-memory limit. A logical Result or Task does not claim ownership of
an entire physical Arc allocation. The fixed tables are finite implementation
bounds, not replacement resource grants. Pure root calls and uncontended sync
do not bootstrap a concurrency runtime.

The bounded Wait registry also owns 32 fixed intrusive node slots in the
component's original linear memory. A slot is reserved before Wait/Timer
admission, initialized only after admission, removed before logical settlement,
and reused only after the node is no longer registered. This avoids inventing a
separate Native owner and System allocation for every temporary wait while
retaining the original Wait/Timer limits, identities and admission failures.
The compiler programme runs the 11 wait-driver controls and eight synchronization
controls, in addition to the ten TLS controls, before producing any sysroot.

Join waits for actual TLS completion and the separately authenticated final
frame/stack boundary, rather than a filled Packet alone. Ordinary waits use the
engine's eligible queue; only the known newly created Ready child uses explicit
promotion during initialization. A thread in an engine host wait is never
manually promoted. No Runtime/state borrow crosses a host admission, allocation,
wait, callback or user destructor.

The captured `futures-executor` 0.3.31 source overlay preserves the ordinary
ThreadPool constructors, original mpsc queue separation, original UnparkMutex
and enter protocol. It authenticates the package archive and four upstream
source files. Target selection does not enable a feature or replace host-side
build dependencies. Each real worker transfers one retained pool Arc into its
exact canonical PAL child. TLS and frame notifications are separate; release
follows actual context retirement on another live stack. Root drain never polls
user futures as a substitute worker. Accepted futures remain live through
their real future destructor and final wake-handle drop. Closing workers cannot
silently accept work: a continuation requires a separately admitted successor
generation, and old Close messages cannot close that successor.

Normal capture embeds the selected modules into the original authenticated
`src/lib.rs`. Only that existing file and its Cargo vendor checksum change;
generic dependency transformations remain replacement-only. The normal builder
reproduces the port from original CAS bytes and rejects a stale recipe, changed
output, unknown runtime version or changed archive. Local packages with the same
name do not acquire a registry runtime patch. The ordinary creator declares the
runtime and clock dependencies and includes them in normal binding generation.
Only the macro's `generate_all` option changes: application function bodies,
Cargo features, requested limits and grants stay intact. This source route has four focused
capture/Prepared/creator controls. Those source controls alone establish no
compilation; actual compiler observations follow below.

The first selected ThreadPool profile explicitly refuses `after_start` and
`before_stop` hooks with `io::ErrorKind::Unsupported` before pool owner admission,
channel or Arc allocation. Keeping a hook as a successor recipe would change
the original observable capture-Drop lifetime; dropping it would skip requested
successor callbacks. The original upstream hook test is retained as original
source and is not claimed to pass for this finite selected profile.

`rust_standard_sysroot_build.py --threads` prepares the jointly selected std
sources in an owned temporary tree and uses the existing locked offline build
route. It has a distinct build profile and conditional recipe, refuses combined
logging/entropy selection in this first profile, and never changes an installed
compiler. [Run 39833272771](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/39833272771)
compiled this sysroot and the original context utility at source
`64effa838840fb50b95ee11f4dda64b883f1a3a3`. All 86 source identities and
27 manifest files were verified; the complete 29-file artifact is 76,683,777
bytes. Sysroot identity is
`sha256:e1aee58616abccac3a53516684c71210ac85e69979d598a49299efd9b40b5a72`.
The earlier nine std diagnostics remain failed historical observations. This
establishes compiler inputs only, with every runtime qualification flag false.

The explicit `rust-context` compiler utility composes the existing stack/entry,
root and original Native-admission transforms, preserving each intermediate
digest. Its separate final-component command verifies the existing native
admission routing. Both receipts keep runtime enablement, private executor graph
authentication and checkpoint qualification false.

The later source-only `--ordinary-core` route prepares the actual public WIT
core export and missing typed Native import without an application marker. It
attaches the context before canonical allocation, preserves each allocator
caller's actual stack pointer, and retains the installed root and logical
owners until the real post-return cleanup returns. Async drain and TLS finish
remain in the public export; the final detached postlude is still System-only.
Original allocator/post-return bodies are retained, not replaced with models.
Their complete private graph and callback behavior are not yet authenticated.
Run `39845781774` at `e54b298b241050f5ce3badc63d39b30a968b4df7`
compiled this new utility and passed all 70 source mechanism controls, including
the four new encoded cases. It rebuilt the selected std and completed normal
capture, then refused the original source/CAS archive's 32MiB expanded bound
before application compilation. It did not execute an application or guest.

The workflow's explicit default-false `application-diagnostic` input compiles
one ordinary captured `futures-executor 0.3.31` application using its default
ThreadPool constructors. The successful original diagnostic used `lto=true`.
The selected THREAD compiler boundary now records `profile.release.lto=false`
as an explicit Cargo configuration, preserving original application Cargo/CAS
bytes and other profiles while retaining compiler object boundaries for the
private graph. It reuses normal
source capture, Prepared checks, isolated compilation and exact executable
approval, retaining the actual core or first compiler/transform failure. It
does not open the production component selector, write BUILD-COMPLETE, package,
sign, invoke a guest or claim progress semantics. New source identities retain
the existing 256-file/16MiB bound; logs, 180-second command bounds, 600-second
diagnostic deadline and 128MiB aggregate artifact cap are unchanged. Full
compiler-distribution guards remain: cross-job installation metadata can differ,
so this joint job builds the selected sysroot with its actual compiler rather
than claiming automatic artifact reuse.

The original normal capture includes the complete native dependency closure,
including host packages. Its unique source/CAS exceeds 32MiB expanded even
though the observed partial archive compresses to 6,658,554 bytes. The diagnostic
therefore explicitly permits at most 128MiB expanded source/CAS in its one
32MiB gzip archive; the 4MiB individual-file and 32,768-entry bounds remain.
It retains the complete accepted lock and source/CAS byte inventory before
compression or an expanded-size refusal, and full digests before compression.
This preserves every original captured path and leaves the outer 128MiB cap
unchanged. It does not authorize larger compiler products or runtime enablement.

Run `39849348413` compiled and validated the original 207,732-byte application
core with ordinary `lto=true`, then refused `rust-root-linker-stack-range`.
The pinned linker placed its real stack at `[0, 1,048,576)`, while both the
selected runtime and context transform require non-null stack bounds. The
selected THREAD compiler boundary therefore explicitly passes the supported
`--no-stack-first` linker flag, placing the real stack after static data. It
keeps the original null, alignment, range and minimum-size guards and consumes
the actual linker-exported bounds; it does not manufacture post-link addresses.
Other profiles keep their original flags.

Run `39850836555` at `728f3b9715e6b763912e820124604db793436952`
passed the complete bounded compiler diagnostic and all final source, compiler,
isolation and Prepared checks. It compiled the authentic captured ordinary
application with `lto=true`, validated its 207,731-byte original core, derived
the 194,957-byte owned core and validated that output. Its actual linker stack
is `[25,664, 1,074,240)`, exactly 1MiB, within 17 initial memory pages. Static
data ends at 24,968; the derived core retains the original memory/data and
exported stack bounds. The complete retained artifact is 108,293,674 bytes.
All 169 Git source identities, 62 artifact rows and 7,094 archived source/CAS
entries were independently checked. This establishes the actual compiler
boundary, with every private-graph, canonical-body, checkpoint and runtime
qualification gate still false. No component or guest was signed or executed.

Run `39858644814` at `cfede0b2d663ea824102745882925efca39a95ca`
passed the selected `lto=false` compiler observation and all final original-source,
compiler-distribution, isolation and Prepared checks, including all 70 source
mechanism cases. Its authentic captured executor rlib is 301,772 bytes,
`sha256:00ef3bef5558e844bf12ccfa91906e15bea1ffd4e6dcedfb49e6dfb3c9f04b41`.
The original core is 262,563 bytes,
`sha256:425f6fbedf2835ce7ab5a2e126fbbd7564998c03703f9b360f04f859158ff203`;
the validated derived core is 247,965 bytes,
`sha256:051f03dfd7d98774a7b2a482a52bec86306e26d13ab556385f8d958806325ca3`.
The sole retained ZIP is 52,035,991 bytes,
`sha256:db72eff1f6e73ed5cb53a24c9ed5bc1876247299b8267b400efe126684b4c7ea`.
Its 66 closed files total 108,798,949 expanded bytes. All 64 artifact rows,
169 exact Git inputs and 7,094 original source/CAS paths (102,991,172 bytes)
were independently hash-checked. The same job rebuilt its strict sysroot;
this is no automatic cache/distribution reuse permission. The effective Cargo
configuration, actual rustc command output and authentic compiler-artifact row
are retained. This supplies original object inputs, not whole private-body,
canonical ABI, checkpoint or runtime qualification. Every such gate remains
false; no component or guest was signed or executed.

Run [39877020838](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/39877020838)
at `28059f343bbd954e3e6614c5a24593897cc0c294` passed the rebuilt context
utility, all 72 source mechanism cases, all 12 actual Rust-emitted wrapper
engine outcomes, strict same-job std and the original captured application.
Its explicit std/application source-prefix remaps remove temporary source-path
bytes from the observed original private graph. Complete original-body and
relocation observations cover 469 function and 756 data definitions; five
private callback targets leave the ordinary table, and six checked owner
dispatches preserve the genuine Source fallback. These observations remain
source evidence until the immutable native catalogue and final component graph
independently authenticate them.

The original core is 262,436 bytes,
`sha256:583e2353a8405db569e61cb3269b3643aff39374c1e2d83cc970cc033604edec`;
the validated guarded core is 248,043 bytes,
`sha256:ba2014e3f4d14c428b93c100a011afbb2f7995436e858108292dbbd70a720519`.
Actual original linker memory reserves Root `[26,256, 1,074,832)` and a distinct
64KiB System stack `[1,074,832, 1,140,368)` within 1,179,648 initial bytes.
The original static result area is 25,544, disjoint from all 756 observed
private data ranges. Result tag/pointer/length are captured before accepted-work
drain and checked afterward; nonempty results must remain in original heap
memory. Canonical allocation failure reaches the source-bound `panic_fmt`
function 531, mapped to 532 by public preparation. Its installed System-only
trap precedes the original prologue/TLS/hook path; normal Root instructions
remain under the existing reencoder. The emitted controls prove that System
panic invokes no hook/context lookup and that normal Root panic retains its
hook. Failure/trap establishes no successful cleanup or refund.

The sole retained ZIP is 52,246,859 bytes,
`sha256:76e11dc5d099d353d027b5e946ec7624f5c7bc90110f4844fc9aff387f2afdc6`.
All 87 files (109,770,851 expanded bytes), 85 manifest rows, 217 exact Git
inputs (2,338,817 bytes), 7,094 source/CAS paths (102,991,172 bytes) and 8,977
accepted file references were independently checked. The compiler-distribution
identity is `sha256:16017bec70a8df1c23e841a42b08f8719f18d59f5f18310647bb61ed0d4201ca`;
its same-job sysroot identity is
`sha256:8b2b96e015168624bb2fd0b5f26eebf7b06496ba60d8f3d2968a32f2687086b4`.
The prior `ec11ecf` run's canonical indirect-path refusal remains recorded;
its distribution receipt is not reused. Normal builder, native catalogue,
canonical-body, checkpoint and runtime qualification flags remain false.
No normal component, signed Rust guest or runtime ThreadPool was executed.

The preceding retained compiler origin is
[run 41058624633](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/41058624633)
at exact source `9106147f83a2e19c8b1be16b9eb5d55e39512bde`. Its job
`124073347987` passed and produced sole artifact `12978203439`, 55,102,784
compressed bytes with SHA-256
`6570db47d0c9657b3375d66c0ddd720cbc2c05fcce61b48d3d2b9ae7ff47dbf2`.
The retained four-member reader verified the 262,760-byte original core
(`sha256:32d45c689b53d41e6a4797e4a293c3a41ad5a3e7219407632101cf3858a18468`)
and 514,214-byte wrapped component
(`sha256:ad791f7486361d73f69b4b4a7b0bc57f5b5094d63cc3d5d2beddef560f9003dd`).
No executable from that compiler artifact is invoked during retrieval, and the
compiler observation alone still establishes no signed runtime result.

The current retained compiler origin is exact-head
[run 41094795688](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/41094795688)
at source `79911762b366381d7dc61da12d1b5e9aba2b3222`. Job `124197667917`
passed the 29 native controls, 76 source controls, ordinary application compile,
Linux component proof and fixed retained-evidence bound. Its sole artifact
`12996890774` is 53,110,361 compressed bytes with SHA-256
`1adc79551de5dfd54255c9fba50346a18161eeec3d01c2c097f06e69b8251e86`.
Independent download verified all 125 archive members and the four selected
preimages, including the 262,561-byte repaired core
(`sha256:1016bc74d96585be6943d2b1396cf79ebd8f1fa66828a321d2ee251827431bcc`).
That core and the reviewed Linux envelope produce the 513,900-byte wrapped
component (`sha256:c6d1156c12cc8464682e49ccc1763c1c68a5347266d1e71efa2b7b786f2cefc5`).
The earlier artifacts and member identities remain recorded separately. This
compiler success still establishes no signed runtime result.

Signed run `41101952346` reached that unchanged application/library path at
component `sha256:c6d1156c12cc8464682e49ccc1763c1c68a5347266d1e71efa2b7b786f2cefc5`,
but the first `pools-cold` call trapped before producing a typed result. The
earlier stack-overflow label and per-key TLS hypothesis are retained as failed
historical diagnoses; neither establishes the current cause.

The bounded follow-up in
[run 41106326690](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/41106326690)
at exact diagnostic source `48a6198bd31f88a4a3bd735dce03042de3a72918`
reproduced the same component, fuel (`422285`), peak memory (`5692098`) and
zero-effect trap. Its eight numeric frames put `Lease::acquire` at the panic
format branch for `TLS owner admission rejected`; panic bookkeeping then entered
`panic_count` TLS and the top frame reached the private stack-lower-bound guard.
The guard is therefore secondary, not evidence that a larger stack is needed.

Source reconciliation found the accounting defect below the unchanged library:
each context was already allocated under its own Native owner (or was the fixed
root record), yet its first bounded TLS entries required a second allocation and
owner. The repair embeds the first 32 entries in that context. Fixed-root entries
manufacture no owner; overflow blocks still require continuation-backed Native
admission before each actual System allocation, remain under the unchanged
linear-memory and owner limits, free before settlement and must leave a null TLS
table. The ten focused controls now cover fixed-root entries, dynamically owned
contexts, a 64-key inline-plus-overflow case and refusal of the 65th key under
the original two-owner bound. A fresh compiler/native/signed hosted result is
still required before runtime acceptance.

Other validation includes source/preimage controls and metadata typechecks
with explicit public-wrapper/ABI ports. Earlier native source controls exercise
the actual registry, wait, TLS and lifecycle bodies with explicit reference
boundaries; they do not execute an actual canonical Rust child, rebuilt std,
published ThreadPool or signed component. Six current source-selection cases
cover exact inverse selectors, runtime closure, legacy recipe preservation and
captured executor refusal paths. Metadata typechecking supplements those cases.

Before any supported runtime claim, the remaining minimum delivery is:

1. Bind the immutable host-owned original-object catalogue and recompute the
   complete normal component graph, including the distinct Rust40 cooperative
   ABI and exact ready handoffs.
2. Execute the normal captured target-side executor/std route with its complete
   original capture/patch identities; source integration alone is insufficient.
3. Authenticate the final private pool bridge callsites, table/callback targets,
   original Arc origin and all post-TLS/frame destructor paths. A private symbol
   or opaque serial alone is not authority to transfer or retire a pool.
4. Assemble and sign actual ordinary thread/default ThreadPool workloads and
   execute independent queues, eligible sibling progress, join/TLS/sync/timer,
   cancellation/panic/trap, limits, root-closing continuations and fresh-tenant
   cleanup under the original ledger.
5. Implement and qualify safe compiler checkpoints in reachable dependency CPU
   loops. Fuel termination does not establish fairness. Approved networking and
   reactor integration retain their separate gates.

Issues #743 and #689 remain open. These sources do not establish all standard
threading, Tokio/Rayon, hook, socket, multicore or general crates.io support.
