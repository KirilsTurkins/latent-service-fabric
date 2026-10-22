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
runtime and clock dependencies while preserving application source, Cargo
features, requested limits and grants. This source route has four focused
capture/Prepared/creator controls; it has not compiled an ordinary guest.

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
compiler. This option has not yet been executed. A successful future sysroot
build is still only a compiler input, not runtime qualification.

The explicit `rust-context` compiler utility composes the existing stack/entry,
root and original Native-admission transforms, preserving each intermediate
digest. Its separate final-component command verifies the existing native
admission routing. Both receipts keep runtime enablement, private executor graph
authentication and checkpoint qualification false. This new utility has not
yet been compiled or executed.

Current validation consists of source/preimage controls and metadata typechecks
with explicit public-wrapper/ABI ports. Earlier native source controls exercise
the actual registry, wait, TLS and lifecycle bodies with explicit reference
boundaries; they do not execute an actual canonical Rust child, rebuilt std,
published ThreadPool or signed component. Six current source-selection cases
cover exact inverse selectors, runtime closure, legacy recipe preservation and
captured executor refusal paths. Metadata typechecking supplements those cases.

Before any supported runtime claim, the remaining minimum delivery is:

1. Compile the jointly selected sysroot and the actual `rust-context` utility.
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
