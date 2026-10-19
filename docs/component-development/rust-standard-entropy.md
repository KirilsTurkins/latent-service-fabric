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
These are not signed component qualification. A fresh owned sysroot, actual
offline dependency build and signed ordinary-library programme remain required
before this source delivery can satisfy the facility execution gate. No FIPS,
statistical quality, concurrency or transactional replay claim is made.
