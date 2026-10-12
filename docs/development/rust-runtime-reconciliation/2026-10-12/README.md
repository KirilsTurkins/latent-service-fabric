# Rust snapshot reconciliation

PR #902 retains the useful Rust clock, logical TLS, stack transform and
owned-thread bootstrap from its original `0be99712751a4b67830914cba42d060f091219db`
snapshot, reconciled with development `ab4e174c`. The overlapping clock source
from #907 (`0114e05a6a5c0a08f4e0729b00bbd3da414f2767`) is preserved here. Unrelated
SDK/frontend changes already reconciled in development stay with their current
owners. Both source snapshots retain their historical branches.

The live bodies and comments of #743, #689 and #683 were reviewed on
2026-10-12. Their cleanup comments explicitly record incomplete ordinary Rust
thread/default-runtime/client qualification. This reconciliation closes none of
those tickets.

## Current delivered boundary

The owned clock-only std builder now builds the authenticated Rust 1.97.1 source
and its offline vendor closure, captures the compiler distribution and selected
source, and records each actual emitted library. It selects the successful Cargo
artifact graph instead of globbing a cache, which could contain incompatible
libraries from an earlier failed attempt. The previously unexecuted proposed
recipe needed `-Zforce-unstable-if-unmarked`; the actual failed build is retained.
Current engine/bindgen assertions stay exact: Wasmtime 48.0.5 and wit-bindgen
0.62.0. The old TLS snapshot's 48.0.4 pins were stale after the development merge.

The maintained clock driver builds an ordinary `SystemTime::now` component
against that emitted std graph. It invokes no application SDK clock or executor.
The actual component imports only `latent:clock/wall@0.1.0` and exports the
test fixture's `read` function. A separately authenticated native executable
admits it through the existing cryptographic test publisher/builder and runs
the production current capability broker. Two successful invocations create two
fresh Stores and make four actual clock imports. Policy revocation denies a
subsequent invocation before another clock sample. Stores, broker sessions,
buffers, calls and original instance reservations retire after each attempt.

The fixture's signers qualify the admission protocol for the actual compiled
input. They do not prove production builder trust, release qualification,
automatic std-profile selection or default executor/client compatibility. The
native trust/policy directories use the ordinary Linux temporary filesystem;
a first attempt on a Windows-mounted receipt filesystem failed before guest
execution and is retained with that original status.

## Executed local evidence

- Four native clock PAL controls: passed with explicit fake host imports.
- Eighteen isolated native TLS controls: passed, one process per case. Failed
  destructor/sentinel scenarios keep their required owners charged.
- Eleven encoded-Wasm stack/thread-entry controls: passed.
- Thirty-six focused Python source/build controls: passed.
- Nine existing signed clock-currentness cases: passed.
- One actual rebuilt-std ordinary clock case: passed explicitly with its prepared
  input; its registered ignore remains a real input prerequisite.
- Actual locked offline std build: fourteen emitted target libraries; current
  graph/source/recipe/compiler/component identities are retained by the driver.

These finite controls measure actual execution or source behavior only within
their stated boundaries. They establish no allocator/RSS sizing, no 100,000-scale
campaign, and no broader runtime fairness or publication claim. Raw compiler
outputs, failed attempts, generated binaries and signing material are excluded
from this source handoff.

## Remaining ticket requirements

| Ticket | Requirements still needed |
| --- | --- |
| #743 | Distributed authenticated sysroot/default builder selection; ordinary logical thread start/join/identity and TLS; contended mutex/condition/channel parking; per-canonical-thread native stack admission and actual fiber retirement; timers/recurrence/drain; named default executor/reactor and blocking-task behavior; safe compiler checkpoints through dependencies/unsafe regions; original-ledger count/stack/queue/memory exhaustion, late-wake and cross-tenant qualification. |
| #689 | At least two unchanged third-party HTTP clients and a new external developer crate through ordinary constructors and the shared supported runtime; default socket/reactor paths over approved authority; all prescribed typed/stream HTTP denial, response, cancellation, uncertain POST, drop/drain, lifecycle and footprint cases. |
| #683 | Full signed third-party/transitive/immutable-resource and outside-checkout/private graph qualification; approved build-tool containment, cancellation, tamper/change controls; authoring/private/watch lifecycle and current source/profile/patch provenance. |

The TLS/stack/thread source remains gated. Its Wasm exited word cannot prove
native fiber retirement, and the activation's current metadata owner does not
fund an unadmitted engine stack. No standard-thread success stub, inline spawn,
package allowlist, custom application executor, grant broadening or guest quota
increase is introduced.

The source and reproducible driver are described in
[the runtime source README](../../../../sdk/rust-standard-runtime/README.md).
