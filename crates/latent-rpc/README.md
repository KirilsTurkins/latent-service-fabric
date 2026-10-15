# latent-rpc

Build-generated Protobuf messages, Tonic clients/servers and descriptor-set ownership, plus checked platform-error and transaction conversions. This is the common wire schema layer for operator clients and node adapters.

Generated server wrappers are transport types, not service implementations. No listener, authentication policy, state engine or dispatcher is installed merely by depending on this crate.

## Responsibilities and architecture

| Source | Responsibility |
| --- | --- |
| [build.rs](build.rs) | Checks the exhaustive sorted Protobuf input manifest and generates code using the pinned vendored protoc. |
| [src/lib.rs](src/lib.rs) | control::v1, invocation::v1, transaction::v1 and FILE_DESCRIPTOR_SET exports. |
| [src/platform_error.rs](src/platform_error.rs) | Loss-preserving checked platform error projection across the wire. |
| [src/phase4.rs](src/phase4.rs) | Bounded transaction/dispatcher/recovery wire associations and conversion helpers. |
| [tests/generated_services.rs](tests/generated_services.rs) | Compile coverage for generated client/server surfaces and descriptor ownership. |

## Execution and ownership

1. Edit authoritative `.proto` files and the exhaustive input manifest together.
2. Cargo generates messages, clients, server traits/wrappers and descriptors into OUT_DIR.
3. Concrete adapters validate full-width counters, optional-field presence and request/reply identities before converting to domain values.
4. `latent-wire` and client SDKs provide execution and transport ownership around those messages.

## Integration boundaries

Keep generated code out of the source authority directories. A transaction receipt preserves historical facts but does not authorize another attempt. The schema can expose planned ports before a production adapter is qualified; use the service implementation and installed-runtime guides to establish availability.

## Dependencies and build

Direct workspace dependencies: [latent-core](../latent-core/README.md).

Consumers with normal workspace dependency edges include [latentd](../../apps/latentd/README.md), [latent](../../apps/latent/README.md), [latent-wire](../latent-wire/README.md), [latent-sdk](../../sdk/rust/README.md), [latent-optimization-bench](../../tools/optimization-bench/README.md). Optional features still gate the selected graph; target-specific and test edges are also declared in the manifests.

Use [Cargo.toml](Cargo.toml) for external dependencies, target gates and test/build edges; [the workspace manifest](../../Cargo.toml) and [the toolchain guide](../../docs/development/toolchain.md) own current pins. Dependency presence does not install a runtime service.

## Tests and verification

The [package entry point](src/lib.rs) and the module links above are the source map. [The workspace package guide](../../docs/development/workspace-packages.md) explains feature/target selection, generated inputs and the registered test workflow.

Inspect a registered suite from the repository root without building or running it:

```sh
python3 tools/test.py explain --suite latent-rpc.lib.latent-rpc
```

Use `list --output json` to find the remaining package targets. Follow the suite's recipe, platform and prerequisites for preparation, discovery and execution; a registration or compile-only check is not a passing execution/qualification result.

Representative source tests (not a complete coverage inventory):

- [`applying_plan_preserves_original_cas_action_reason_and_publication`](src/phase4/effect_management/tests.rs)
- [`historical_receipt_keeps_expired_plan_and_independent_unknown_audit`](src/phase4/effect_management/tests.rs)
- [`fresh_read_publication_does_not_rewrite_original_plan`](src/phase4/effect_management/tests.rs)
- [`lookup_and_dedup_safety_need_original_attempt_and_finite_horizon`](src/phase4/effect_management/tests.rs)

Integration targets: [tests/generated_services.rs](tests/generated_services.rs), [tests/platform_error_round_trip.rs](tests/platform_error_round_trip.rs).

## Related documentation

- [latent-api.protos](../../api/proto/latent-api.protos)
- [Executable build foundation](../../docs/development/build-foundation.md)
- [API surface map](../../docs/api-surface.md)
- [Installed transaction RPCs](../../docs/development/installed-transaction-rpc.md)
- [Platform error model](../../docs/protocol/platform-errors.md)
- [Workspace package index](../README.md)
- [Architecture index](../../ARCHITECTURE.md)
