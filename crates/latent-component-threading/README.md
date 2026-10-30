# latent-component-threading

Bounded post-link transforms and final Component Model routing authentication
for owned continuations. The shared implementation now includes the original
Rust canonical-child route, the C context144 synchronous cooperative route and
the Rust context40 synchronous cooperative route. These are separate finite
source/component profiles, not general pthread, `std::thread` or executor support.
The runtime must explicitly select and admit the matching implementation;
default engine thread creation remains disabled.

The crate owns immutable input inspection, transformation and receipts. It has
no dependency on the node, capability broker, activation ledger or Wasmtime.
A successful receipt confers no runtime authority and releases no resource.

## Responsibilities and architecture

| Source | Responsibility |
| --- | --- |
| [src/lib.rs](src/lib.rs) | Exact preimage, bounded core-module inspection, shadow-stack access rewriting and original/derived identities. |
| [src/thread_entry.rs](src/thread_entry.rs) | Preserve the callback index while wrapping its translated body with checked context attach and detach. |
| [src/root.rs](src/root.rs) | Authenticate and wrap the root bootstrap and its original stack range. |
| [src/admission.rs](src/admission.rs) | Route raw canonical creation through one fixed Native admission wrapper. |
| [src/component.rs](src/component.rs) | Authenticate the actual main, encoder shim and fixup graph and its sole creation/admission route. |
| [src/c_context.rs](src/c_context.rs), [src/c_abi.rs](src/c_abi.rs), [src/c_lifecycle.rs](src/c_lifecycle.rs) | C stack/TLS context, canonical ABI and charged lifecycle derivation. |
| [src/c_preimage.rs](src/c_preimage.rs) | Bound and independently recompute the supplied C original core before accepting its final component graph. |
| [src/rust_objects.rs](src/rust_objects.rs), [src/rust_component.rs](src/rust_component.rs) | Authenticate the reviewed original Rust object graph and recompute the closed synchronous component envelope. |
| [src/bin/c-context.rs](src/bin/c-context.rs), [src/bin/rust-context.rs](src/bin/rust-context.rs) | Explicit compiler-side entry points over those same source checks. |

## Execution and ownership

1. The caller supplies complete immutable bytes and, for a transform, their exact
   SHA-256 preimage. The original 8 MiB, 65,534 function and 2,000,000 operator
   bounds apply before translation.
2. Core transforms preserve original function and table identities, unrelated
   instructions, data and custom sections. New helpers are appended. Original
   debug offsets remain explicitly unqualified after code translation.
3. Select the exact context/profile: the Rust context40 or C context144 path,
   its unshared memory32, original source/objects and fixed wrappers. Slot 1,
   stack bounds, Task identity and lifecycle phases are checked as part of that
   profile; changing a label or matching function signature is insufficient.
4. Final routing verification traces actual core module, instance, alias,
   canonical creation and lowering identities. Labels or equal function types
   cannot stand in for that graph. Dynamic code, parallel spawning, raw creator
   escapes, unapproved tables and a guest-supplied admission provider fail.
5. The caller retains every input/output buffer and runtime owner. Logical
   frame exit is distinct from native fiber retirement. The original host ledger
   and physical stack destructor remain responsible for their resources.

No language profile is accepted by name substitution. The C and Rust adapters
authenticate their own context, callbacks, bootstrap and teardown. A future
adapter must establish its own complete contract. The
[Rust source facade](../../sdk/rust-standard-runtime/stack-transform/README.md)
retains its existing CLI and independent lock. A captured compiler must include
the complete common source closure; a path on a developer host is not a captured
compiler input.

## Dependencies and verification

[Cargo.toml](Cargo.toml) preserves the implementation's exact wasmparser and
wasm-encoder 0.259.0 and SHA-2 0.11.0 pins. Runtime workspace parser and digest
versions are unchanged. The package follows the workspace MSRV and forbids unsafe
code; it does not link a runtime engine.

Inspect its registered source controls through the repository test front door:

```sh
python3 tools/test.py explain --suite latent-component-threading.lib.latent-component-threading
```

The independently locked facade retains its own manifest and CLI controls;
root workspace test selection does not include that package implicitly. The
[local runner guide](../../docs/development/local-tests.md) owns preparation and
exact execution. Source/encoder checks, authenticated object graphs and actual
native component invocation establish different boundaries. The original
[source receipt](../../docs/testing/evidence/shared-component-threading-source-2026-10-16.json),
[C preparation contract](../../docs/development/c-thread-preparation.md) and
[Rust native source programme](../../docs/testing/rust-owned-thread-native-source.md)
retain their own exact selectors, sources and remaining gates. An earlier
successful graph does not qualify a later compiler/sysroot or arbitrary WIT.

See the [workspace index](../README.md), [Rust runtime investigation](../../sdk/rust-standard-runtime/README.md)
and [activation ownership](../../docs/runtime/activation-runtime.md) for the
remaining runtime integration boundaries.
