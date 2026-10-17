# latent-component-threading

Bounded post-link transforms and final Component Model routing authentication
for owned continuations. This crate supplies the implementation shared by the
Rust source-profile CLI and future language adapters. The only accepted profile
today is the explicit Rust memory32 context layout. C, pthreads, Rust `std::thread`
and engine thread creation remain unqualified and disabled.

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

## Execution and ownership

1. The caller supplies complete immutable bytes and, for a transform, their exact
   SHA-256 preimage. The original 8 MiB, 65,534 function and 2,000,000 operator
   bounds apply before translation.
2. Core transforms preserve original function and table identities, unrelated
   instructions, data and custom sections. New helpers are appended. Original
   debug offsets remain explicitly unqualified after code translation.
3. The current profile uses one unshared memory32 and a 40-byte context aligned
   to eight bytes. Slot 1 identifies the context; stack bounds, Task identity and
   lifecycle phases must match the fixed wrappers.
4. Final routing verification traces actual core module, instance, alias,
   canonical creation and lowering identities. Labels or equal function types
   cannot stand in for that graph. Dynamic code, parallel spawning, raw creator
   escapes, unapproved tables and a guest-supplied admission provider fail.
5. The caller retains every input/output buffer and runtime owner. Logical
   frame exit is distinct from native fiber retirement. The original host ledger
   and physical stack destructor remain responsible for their resources.

No C profile is accepted by name substitution. A future language adapter must
authenticate its own context, callbacks, bootstrap and teardown before selecting
the common implementation. The [Rust source facade](../../sdk/rust-standard-runtime/stack-transform/README.md)
retains its existing CLI and independent lock. A captured compiler must include
the complete common source closure; a path on a developer host is not a captured
compiler input.

## Dependencies and verification

[Cargo.toml](Cargo.toml) preserves the implementation's exact wasmparser and
wasm-encoder 0.259.0 and SHA-2 0.10.9 pins. Runtime workspace parser and digest
versions are unchanged. The package follows the workspace MSRV and forbids unsafe
code; it does not link a runtime engine.

Run its source controls with:

```sh
cargo test --locked -p latent-component-threading
cargo test --locked --manifest-path sdk/rust-standard-runtime/stack-transform/Cargo.toml
```

The 20 original transform unit controls remain in this crate, and the facade's
CLI preimage control remains in its original package. The maintained Rust workflow
also runs the original 17 actual encoded component routing controls, including
root and nested-interface positives and validated malicious graph negatives.
These are source and encoder checks, not signed standard-runtime qualification.
The [source receipt](../../docs/testing/evidence/shared-component-threading-source-2026-10-16.json)
records the actual local controls and the remaining hosted workspace/MSRV gates.

See the [workspace index](../README.md), [Rust runtime investigation](../../sdk/rust-standard-runtime/README.md)
and [activation ownership](../../docs/runtime/activation-runtime.md) for the
remaining runtime integration boundaries.
