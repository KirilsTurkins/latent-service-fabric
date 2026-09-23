# C guest SDK

Start with [Create your own C capsule](../../docs/component-development/c-authoring.md).
It creates an independent project and walks through WIT, compilation, packaging,
signing, enforced admission, publication, deployment, invocation and cleanup.
This guest SDK is separate from the external C control-plane client in `../c`.

The maintained toolchain is Zig 0.16.0 (`zig cc`, C11, `wasm32-wasi`, `-O2`),
wit-bindgen 0.62.0 and wasm-tools 1.254.0. Generated bindings preserve WIT
identity, async imports, `uint64_t`, UTF-8 strings, records, lists, options,
results and owned/borrowed resources. They are generated from the selected WIT,
not a handwritten second ABI. The contract derivation tool explicitly rejects
unsupported public shapes; see the [guest reference](../../docs/component-development/guest-sdk.md).

The reactor has a 64 KiB stack, a finite memory maximum and no thread runtime.
Zig's bundled libc supplies allocation. Component construction rejects ambient
WASI imports: filesystem, sockets, environment and clocks are not automatically
available. Applications do not create provider clients, grants or credentials.
The ordinary host deployment policy remains the only source of authority.

## Owners and asynchronous calls

`include/lsf/ownership.h` defines an explicit bounded scope (32 entries plus a
caller-selected byte limit). Allocation, adoption, detach and release have
separate ownership meanings. Close runs remaining cleanup in reverse order;
detach transfers ownership without claiming a host-budget refund. A generated
export's post-return owner frees transferred strings. Borrowed literals must
never be freed or returned as owned strings.

`async.h` retains task input and result frames across pending canonical calls,
distinguishes cancellation with and without returned data, and retires subtasks
before clearing context. C provides no borrow checker: copying an owner or
freeing input before a subtask retires is an application bug. Do not keep frames
in globals across invocations. The activation teardown also reclaims memory
when a trap prevents guest cleanup; it does not undo external effects.

`http.h` closes nested response allocations; `streaming.h` and `blob.h` track
affine chunks, request uploads, response bodies and primitive handles.
`secrets.h` zeroizes its owned bytes before freeing them. `service.h` preserves
child result classifications. Events, randomness and metrics use the generated
typed imports directly. Every capability has an executable source under
`examples/` (blob ownership is in `blob.c`). No wrapper retries or grants access.

## Verification

With the pinned tools installed, from the repository root:

```sh
python3 tools/qualify_c_capsules.py --output /tmp/my-fresh-c-qualification
```

The finite Linux gate creates five projects outside the runtime checkout,
compiles their actual editable C sources, checks generated SDK binding hashes,
and executes the printed beginner guide. It also builds the C and Rust
capability peers and runs the admitted Wasmtime tests for every capability.
The real-node gate checks denied authority, declared errors, deadline/cancel/
disconnect cleanup, trap/fuel/memory exhaustion, and fresh calls after failure.
It observes active owners and 5/9/17 dormant deployments with a two-entry shared
code cache; it does not claim production sizing or a full 100k-scale result.

Failed builds retain `BUILD-FAILED.json` and bounded compiler logs. Observations
bind captured inputs, actual tools and outputs; they are operator assertions,
not authenticated source or a complete transitive SBOM. Demo signing occurs
only after compilation in a separate process. The human newcomer review remains
the separate #345 gate.

Measured results and retained failed attempts are documented in the
[developer qualification report](../../docs/development/c-capsule-qualification.md).
