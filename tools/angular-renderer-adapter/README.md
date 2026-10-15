# latent-angular-renderer-adapter

Fixed wasm32 guest adapter between the private synchronous closed JavaScript renderer and the public asynchronous `latent:web/application@0.1.0` contract. The final composed component runs on the generic Wasmtime backend with a fresh Store per render.

No application worker, node-side JavaScript event loop or reusable guest heap is created. The private engine interface must be satisfied inside the composed component.

## Responsibilities and architecture

| Source | Responsibility |
| --- | --- |
| [src/lib.rs](src/lib.rs) | Public handle implementation, response/status/header/frame limits and canonical base64 body handling. |
| [src/abi.rs](src/abi.rs) | Generated WIT bindings and canonical export; sole generated unsafe-code allowance. |
| [src/wire.rs](src/wire.rs) | Bounded private request/document frames and host-sampled identity context. |
| [src/backend.rs](src/backend.rs) | Optional backend-http render data through approved host capability calls. |
| [runtime/timers.js](runtime/timers.js) | Cumulative bounded zero-delay timer and explicit microtask setup before application evaluation. |

## Execution and ownership

1. Compose the adapter and selected closed renderer using exact WIT imports/exports.
2. For each fresh activation, sample principal, lineage, trace and deadline from host context rather than HTTP identity fields.
3. Optionally obtain bounded backend data through the broker, then pass a private request frame to the internal renderer.
4. Validate result/frame/document/header bounds and produce the public response. HEAD/304 describe the representation without returning its body.

## Integration boundaries

`backend-http` selects a concrete optional data path, not ambient networking. Private frames have a 256 KiB request ceiling; returned frames are limited to 1 MiB and HTML to 128 KiB. Timers/microtasks also require host fuel, epochs, memory and cancellation for native Promise work. HTTP delivery/security headers remain with the shared ingress boundary. A native build has no adapter API because the crate is wasm32-gated.

## Dependencies and build

There are no unconditional workspace dependencies. Target-specific and test/build edges, if present, are declared in the manifest.

Cargo features (the manifest owns their exact expansion):

| Feature | Enables |
| --- | --- |
| `backend-http` | No additional feature dependency. |

Use [Cargo.toml](Cargo.toml) for external dependencies, target gates and test/build edges; [the workspace manifest](../../Cargo.toml) and [the toolchain guide](../../docs/development/toolchain.md) own current pins. Dependency presence does not install a runtime service.

## Tests and verification

The [package entry point](src/lib.rs) and the module links above are the source map. [The workspace package guide](../../docs/development/workspace-packages.md) explains feature/target selection, generated inputs and the registered test workflow.

Inspect a registered suite from the repository root without building or running it:

```sh
python3 tools/test.py explain --suite latent-angular-renderer-adapter.cdylib.latent-angular-renderer-adapter
```

Use `list --output json` to find the remaining package targets. Follow the suite's recipe, platform and prerequisites for preparation, discovery and execution; a registration or compile-only check is not a passing execution/qualification result.

## Related documentation

- [Angular in generic execution cells](../../docs/runtime/angular-renderer-runtime.md)
- [Scoped Angular render data](../../docs/runtime/angular-backend-profile.md)
- [Angular renderer execution profile](../../docs/runtime/angular-renderer-profile.md)
- [Build your first Angular application](../../docs/component-development/angular-build.md)
- [componentize-runtime.mjs](../../examples/renderer-profile/componentize-runtime.mjs)
- [ADR-0040: Run the closed Angular adapter in fresh generic Stores](../../adr/0040-run-the-closed-angular-adapter-in-fresh-generic-stores.md)
- [Workspace package index](../../crates/README.md)
- [Architecture index](../../ARCHITECTURE.md)
