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

The seven acquisition/archive/product controls pass on Windows without requiring symlink
creation. The [first hosted attempt](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/38827200516/job/116737305655)
compiled `libjs_static.a`, then failed the original SpiderMonkey include-order
check. Its failed receipt and exact source/log identities remain retained. The
hook header now orders RootingAPI before TypeDecls, and the derived Promise
source includes the hook with the other js headers after the Mozilla headers.
The original checker remains enabled; a full successful build is still required.
Post-build source rechecks compare the acquisition's upstream bare digest with
the shared identity owner's algorithm-prefixed digest. Normal installed header
links must resolve to exact bytes inside the owned build. The static product is
the pinned upstream target `obj/js/src/build/libjs_static.a`; unrelated installed
aliases cannot select another library.
The previous storage-interrupted local attempts remain retained separately.
Engine linkage, compiler splicer identity and signed ordinary-node runtime/HTTP
cases remain required by [#745](https://github.com/KirilsTurkins/latent-service-fabric/issues/745)
and [#691](https://github.com/KirilsTurkins/latent-service-fabric/issues/691).

The subsequent maintained `tools/build_typescript_native_engine.py` consumes
that successful original library receipt and authenticates its exact archive,
library, recipe and normal installed-header identities. It captures the exact
ComponentizeJS and StarlingMonkey source carriers, generates the current jobs
and clocks C ABI with the pinned generator, and applies the existing reviewed
activation and clock source derivations. It combines the original library with
the exact supporting object list from the pinned upstream CMake source. Headers
are materialized into private staging; the original library output is unchanged.

The normal upstream CMake configure/build produces `starlingmonkey_embedding`
in Release mode, with the upstream debugger and Weval options disabled. The
upstream Corrosion import additionally requires the existing Cargo lock.
Configure is limited to 600 seconds, build to 900 seconds with two jobs, and the
whole engine operation to 1200 seconds. The same existing 60-minute source job
runs both stages; the original library and application compiler limits remain
intact. All normal command output, failure receipts and the generated engine
input envelope remain separate from runtime acceptance.

An actual source-only control verified both original carriers, all source
preimages, the exact fresh clock-binding pins and the 22 original supporting
object paths. Four additional controls cover object-list injection, retained
original header/configuration bytes, deadlines and source-carrier preservation.
Normal Linux engine linkage has not yet passed. Even an emitted validated core
is an explicitly unqualified Promise/clock compiler input. Source-built async
import splicing, ordinary signed lifecycle/drain cases, and the default Fetch
and HTTP consumer matrix remain required; this stage does not supply them.
