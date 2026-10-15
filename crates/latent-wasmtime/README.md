# latent-wasmtime

Concrete Component Model execution backend with fresh activation Stores, exact host ABI validation, bounded prepared-code reuse and optional authenticated local AOT reuse. A node-owned factory supplies shared engine/compiler/cache resources; mutable guest state and host capability sessions belong to each invocation.

This is the implemented Wasm backend, not the native-SFI research backend. Existing AOT output is trusted Wasmtime-produced native code loaded through a separate authenticated boundary, never arbitrary uploaded native libraries.

## Responsibilities and architecture

| Source | Responsibility |
| --- | --- |
| [src/factory.rs](src/factory.rs) | Configured engine and shared runtime owner. |
| [src/backend.rs](src/backend.rs) | ExecutionBackend implementation and owned preparation/materialization/invocation paths. |
| [src/config.rs](src/config.rs) | Validated engine limits and explicit isolation profiles; layout participates in identity. |
| [src/cache.rs](src/cache.rs) | Immutable prepared-state cache, finite compilation capacity and actual pin reclamation. |
| [src/compiler.rs](src/compiler.rs) | Fixed owned compiler workers and bounded coalescing. |
| [src/aot.rs](src/aot.rs) | Isolated compiler protocol, provenance, persistent cache and authenticated byte owners. |
| [src/aot/loader.rs](src/aot/loader.rs) | Audited native deserialization boundary after provenance and byte ownership are sealed. |
| [src/host.rs](src/host.rs) | Store-owned host context, resource tables, capability adapters and transaction access. |
| [src/surface.rs](src/surface.rs) | Exact dynamic export/import signatures and resource ownership validation. |
| [src/values.rs](src/values.rs) | Bounded type-directed WIT-value JSON codec. |
| [src/containment.rs](src/containment.rs) | Runtime resource accounting and shared epoch-worker ownership. |

## Execution and ownership

1. Acquire an exact repository-authenticated publication/source and check runtime/preparation compatibility.
2. Reuse immutable code or compile under finite raw/compiler/native-image reservations. Isolated AOT output must pass its protected provenance and byte-ownership boundary before loading.
3. Recheck current publication and import authority, then construct a fresh Store with original activation ledger, limiter, fuel, epoch interruption, cancellation and selected host services.
4. Invoke the validated export asynchronously. Pending calls retain physical ownership; yielding does not evict the Store or free its execution cell.
5. Drop guest and host resources, retire accepted work and report reusable/quarantine cleanup. Prepared cache entries must retain no Store, heap or capability session.

## Integration boundaries

The Phase 0 facade retains echo framing over the shared backend; it is not a second product engine. `aot-test-timings`, `development-clock-fixture`, `development-test-host` and `java-guest-diagnostic` expose explicit measurement/fixture/diagnostic surfaces, not extra application authority. The external profile requires its actual admission/compiler/OS owners; its name alone cannot supply them. In-process Wasmtime isolation does not claim resistance to arbitrary engine/host compromise. Native AOT cache validity remains separate from permission to start a new activation.

## Dependencies and build

Direct workspace dependencies: [latent-packaging](../latent-packaging/README.md), [latent-activation](../latent-activation/README.md), [latent-artifacts](../latent-artifacts/README.md), [latent-audit](../latent-audit/README.md), [latent-component-bindings](../latent-component-bindings/README.md), [latent-core](../latent-core/README.md), [latent-capabilities](../latent-capabilities/README.md), [latent-policy](../latent-policy/README.md), [latent-routing](../latent-routing/README.md), [latent-executor](../latent-executor/README.md), [latent-manifest](../latent-manifest/README.md), [latent-telemetry](../latent-telemetry/README.md).

Consumers with normal workspace dependency edges include [latentd](../../apps/latentd/README.md), [latent-portable-test-host](../../tools/portable-test-host/README.md). Optional features still gate the selected graph; target-specific and test edges are also declared in the manifests.

Cargo features (the manifest owns their exact expansion):

| Feature | Enables |
| --- | --- |
| `aot-test-timings` | No additional feature dependency. |
| `development-clock-fixture` | No additional feature dependency. |
| `development-test-host` | `latent-artifacts/development-test-host`, `latent-policy/development-test-host`, `development-clock-fixture` |
| `java-guest-diagnostic` | No additional feature dependency. |

Use [Cargo.toml](Cargo.toml) for external dependencies, target gates and test/build edges; [the workspace manifest](../../Cargo.toml) and [the toolchain guide](../../docs/development/toolchain.md) own current pins. Dependency presence does not install a runtime service.

## Tests and verification

The [package entry point](src/lib.rs) and the module links above are the source map. [The workspace package guide](../../docs/development/workspace-packages.md) explains feature/target selection, generated inputs and the registered test workflow.

Inspect a registered suite from the repository root without building or running it:

```sh
python3 tools/test.py explain --suite latent-wasmtime.lib.latent-wasmtime
```

Use `list --output json` to find the remaining package targets. Follow the suite's recipe, platform and prerequisites for preparation, discovery and execution; a registration or compile-only check is not a passing execution/qualification result.

Representative source tests (not a complete coverage inventory):

- [`settings_reject_unfunded_mapping_tail_before_any_resource_is_opened`](src/aot/cache/model/tests.rs)
- [`raw_payload_capacity_does_not_falsely_charge_separate_entry_headers`](src/aot/cache/model/tests.rs)
- [`native_observations_use_exact_sealed_source_identities_and_fixed_outcomes`](src/aot/cache/observation/tests.rs)
- [`unscoped_local_source_stays_node_scoped_without_a_package_claim`](src/aot/cache/observation/tests.rs)

Integration targets: [tests/admission.rs](tests/admission.rs), [tests/angular_build.rs](tests/angular_build.rs), [tests/angular_renderer.rs](tests/angular_renderer.rs), [tests/aot_sandbox.rs](tests/aot_sandbox.rs), [tests/aot_supervisor.rs](tests/aot_supervisor.rs), [tests/async_application.rs](tests/async_application.rs), [tests/broker.rs](tests/broker.rs), [tests/capabilities_backend.rs](tests/capabilities_backend.rs), [tests/clock_admission.rs](tests/clock_admission.rs), [tests/containment_backend.rs](tests/containment_backend.rs), [tests/dotnet_guest.rs](tests/dotnet_guest.rs), [tests/echo_backend.rs](tests/echo_backend.rs), [tests/generic_backend.rs](tests/generic_backend.rs), [tests/guest_sdk.rs](tests/guest_sdk.rs), [tests/http.rs](tests/http.rs), [tests/isolated_aot.rs](tests/isolated_aot.rs), [tests/lifecycle.rs](tests/lifecycle.rs), [tests/local_blobs.rs](tests/local_blobs.rs), [tests/local_secrets.rs](tests/local_secrets.rs), [tests/local_service.rs](tests/local_service.rs), [tests/local_service_diagnostics.rs](tests/local_service_diagnostics.rs), [tests/metrics.rs](tests/metrics.rs), [tests/native_aot_cache.rs](tests/native_aot_cache.rs), [tests/nats_events.rs](tests/nats_events.rs), [tests/nats_triggers.rs](tests/nats_triggers.rs), [tests/outbound_streams.rs](tests/outbound_streams.rs), [tests/phase3_resource.rs](tests/phase3_resource.rs), [tests/random.rs](tests/random.rs), [tests/s3_blobs.rs](tests/s3_blobs.rs), [tests/session_admission.rs](tests/session_admission.rs), [tests/streaming_http.rs](tests/streaming_http.rs), [tests/vault_secrets.rs](tests/vault_secrets.rs).

## Related documentation

- [Generic Wasmtime execution](../../docs/runtime/wasmtime.md)
- [Isolated trusted-local AOT compilation and native cache](../../docs/runtime/trusted-aot.md)
- [Execution security profiles](../../docs/runtime/execution-security-profiles.md)
- [Host ABI compatibility profiles](../../docs/runtime/host-abi-profile.md)
- [WIT value payloads](../../docs/protocol/wit-values.md)
- [Bounded asynchronous host I/O](../../docs/runtime/async-host-io.md)
- [Phase 0 activation containment](../../docs/development/activation-containment.md)
- [Workspace package index](../README.md)
- [Architecture index](../../ARCHITECTURE.md)
