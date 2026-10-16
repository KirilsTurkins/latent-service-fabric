# Intrinsic Promise library source build

`tools/build_typescript_promise_library.py` builds a candidate SpiderMonkey
static library through the pinned Firefox tree's normal `mach build`. This
checks the maintained intrinsic Promise hooks and normal public-header export
in the actual upstream build. It does not qualify a ComponentizeJS engine,
compiler splicer, Promise lifecycle, Fetch API or default client library.

The builder streams exact SHA-256/length-pinned Firefox, WASI SDK 30 and
cbindgen 0.29.2 upstream inputs into a fresh outside-checkout directory. All
archive members are validated before extraction, including path, link, device,
duplicate, count, byte and deadline boundaries. Original archives remain
retained and are rechecked after compilation. The existing complete source
preimages select the only three modified upstream files; the normal public
header export installs the exact captured SDK header. Recipe sources and the
selected derived files are checked again after the build.

Use Linux x86-64, pinned Rust 1.97.1 with wasm32-wasip1, Node 24.19.0,
Python 3.13.5, Clang/LLVM 18, autoconf 2.13, m4 and the ordinary build prerequisites.
The existing TypeScript workflow installs those host tools and runs:

```bash
python3 -m unittest tools.tests.test_typescript_promise_library -v
python3 tools/build_typescript_promise_library.py --output "$RUNNER_TEMP/typescript-promise-library"
```

Acquisition is bounded to 600 seconds per original input, the normal cold source
build to 1800 seconds with one build job, and the enclosing operation to 3000
seconds. This source preparation limit is separate from the unchanged 600-second
application compiler qualification. The existing TypeScript job and all of its
commands, guards and 75-minute limit remain intact; a separate 60-minute job
executes this source build and retains its receipt, exact input/derivation
identities, configuration, notices, normal installed headers and static product.
Failure receipts keep their stage and never become runtime qualification.

The five acquisition/archive controls pass on Windows without requiring symlink
creation. The hosted source compilation has been added and remains pending.
The previous storage-interrupted local attempts remain retained separately.
Engine linkage, compiler splicer identity and signed ordinary-node runtime/HTTP
cases remain required by [#745](https://github.com/KirilsTurkins/latent-service-fabric/issues/745)
and [#691](https://github.com/KirilsTurkins/latent-service-fabric/issues/691).
