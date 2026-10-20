# Explicit Rust entropy profile

Select `rust-standard-entropy-v1` or `rust-standard-logging-entropy-v1` when creating
a project with `tools/rust_capsule.py new --runtime-profile`. The creator declares
the existing RANDOM interface in the authoritative world; an operator still has
to install its provider and explicitly grant its operations. The build requires
an exact owned standard runtime built by `tools/rust_standard_sysroot_build.py
--entropy`. Add `--logging` only for the combined profile. Other profiles retain
their original entropy behavior.

The maintained source port supports ordinary `getrandom` 0.3.4 calls under
unchanged dependencies. Native Cargo resolution authenticates the original
registry capture. The selected compiler profile derives its canonical scalar
backend, captures original and transformed files, and updates the vendor file
checksums while preserving the original archive checksum. Build-time validation
reproduces those edits from original content-addressed bytes. Changed source or
recipes require a new normal resolve and exact review. Local packages with the
same name and unknown versions are ordinary captured application code; they do
not receive an automatic runtime patch. Build scripts retain the normal explicit
executable-input approval and isolation requirements.

The same scalar source supplies standard `HashMap` seed creation and the
compiler's underlying standard entropy primitive. Stable Rust does not provide a
stable `std::random` API; the profile does not advertise one. The direct canonical
boundary returns at most 65,536 bytes per request, makes no calls for empty
buffers, and clears partial output on typed provider refusal. Fallible getrandom
calls retain errors; infallible standard seed creation traps on refusal. No
address, clock, fixed seed or ambient OS fallback is installed by this profile.
Provider and activation limits remain separate from the request bound.

Source controls and a standalone Rust reference exercise scalar layout, lengths,
all three provider error ordinals, clearing, guard bytes and fresh source calls.
Their scope is separate from the actual signed programme below. No FIPS,
statistical quality, concurrency or transactional replay claim is made.


The separate `standard-entropy` qualification job builds one owned entropy std
sysroot from the authenticated Rust 1.97.1 archive, then captures an outside
library with ordinary getrandom 0.3.4, rand_core 0.9.3 OsRng, a transitive UTF-8
text resource and a binary resource. Both outside source directories are removed
before the isolated, offline component build. The normal executable-input gate
first refuses the captured build-script/macro closure, including getrandom's
audited build script; only this controlled fixture programme then reviews and
consumes that exact retained request identity. Additional compiler transitive
inputs resolved by normal Cargo retain this same source-bound approval.

The signed programme requires the original 27 node cases plus two before-guest
missing-grant denials and 16 entropy calls. It covers empty, one-byte, 257-byte,
uninitialized, scalar, OsRng, HashMap seeding, 4096-byte and oversized requests;
typed budget denial and an infallible standard-library trap; exact policy
restoration; and fresh activation after denial, trap and fuel exhaustion. Each
executed call must have known outcome, bounded fuel/memory, zero unrelated
outbound/log/effect use and physical process/provider retirement. The 65536-byte
provider aggregate and original invocation budgets are unchanged. This programme
does not claim aggregate-quota exhaustion. The actual owned-std and signed programme passed all 45 invocations in
[run 39341096377](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/39341096377/job/118362565604).
The [retained proof](../testing/evidence/rust-standard-entropy-signed-2026-10-20.json)
binds source, compiler, component, all invocations, 24 provider-idle samples,
40 physical observations and clean reaped shutdown. Exact normal approval covered
both getrandom and the resolved wit-bindgen build scripts. Native helpers and
companions retain historical source attribution; this run does not compile a new
native host. The final runner composition adds only the separately qualified,
default-off .NET entropy campaign. Broader #681 requirements remain open.
