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

`tests/clock_native.rs` exercises this actual PAL source using explicit fake
host clock imports. Run that native reference harness with one test thread;
its evidence does not qualify a guest sysroot, component or runtime.
