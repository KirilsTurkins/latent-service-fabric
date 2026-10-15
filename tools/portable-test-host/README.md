# latent-portable-test-host

Controlled portable component test executable using the production Wasmtime backend and value codec without instantiating a production node. A bounded stdin request selects explicit component/manifest/contract inputs, finite calls, runtime profile and test fixtures; stdout contains one structured portable result.

Volatile test authority and private loopback fixtures are deliberately separate from production signed publication, protected storage and provider installation.

## Responsibilities and architecture

| Source | Responsibility |
| --- | --- |
| [src/main.rs](src/main.rs) | Bounded stdin request, current-thread runtime and one result/error document. |
| [src/request.rs](src/request.rs) | Closed portable request/profile, fixture and full-width clock input validation. |
| [src/runtime.rs](src/runtime.rs) | Production backend/value-codec execution under the portable test owner. |
| [src/providers.rs](src/providers.rs) | Explicit volatile broker policy and test-only owner seals. |
| [src/http_fixture.rs](src/http_fixture.rs) | Bounded private loopback peer for the ordinary production HTTP provider. |

## Execution and ownership

1. The developer test runner supplies a controlled-development portable request with exact artifact inputs.
2. Validate finite calls/limits/fixtures before constructing the local test runtime.
3. Install explicit volatile grants and private fixture endpoints, then invoke the unchanged production backend/codec.
4. Retire fixture/runtime owners and emit a bounded result marked portable and productionNode=false.

## Integration boundaries

Portable tests do not certify native Linux node security, signed admission, transaction storage, container isolation or whole-host resource guarantees. Clock fixtures alter guest-visible readings only; they cannot select an external-capsule security profile. Fixture URLs/bytes are explicit and do not rewrite arbitrary ambient endpoints.

## Dependencies and build

Direct workspace dependencies: [latent-activation](../../crates/latent-activation/README.md), [latent-artifacts](../../crates/latent-artifacts/README.md), [latent-capabilities](../../crates/latent-capabilities/README.md), [latent-core](../../crates/latent-core/README.md), [latent-executor](../../crates/latent-executor/README.md), [latent-http](../../crates/latent-http/README.md), [latent-manifest](../../crates/latent-manifest/README.md), [latent-policy](../../crates/latent-policy/README.md), [latent-routing](../../crates/latent-routing/README.md), [latent-telemetry](../../crates/latent-telemetry/README.md), [latent-wasmtime](../../crates/latent-wasmtime/README.md).

Use [Cargo.toml](Cargo.toml) for external dependencies, target gates and test/build edges; [the workspace manifest](../../Cargo.toml) and [the toolchain guide](../../docs/development/toolchain.md) own current pins. Dependency presence does not install a runtime service.

## Tests and verification

The [package entry point](src/main.rs) and the module links above are the source map. [The workspace package guide](../../docs/development/workspace-packages.md) explains feature/target selection, generated inputs and the registered test workflow.

Inspect a registered suite from the repository root without building or running it:

```sh
python3 tools/test.py explain --suite latent-portable-test-host.bin.latent-portable-test-host
```

Use `list --output json` to find the remaining package targets. Follow the suite's recipe, platform and prerequisites for preparation, discovery and execution; a registration or compile-only check is not a passing execution/qualification result.

Representative source tests (not a complete coverage inventory):

- [`test_owner_seals_are_distinct_and_retire_on_drop`](src/tests.rs)
- [`test_owner_rejects_mismatched_bytes_and_tenant`](src/tests.rs)
- [`guest_clock_fixture_is_explicit_full_width_and_rejects_ambiguous_values`](src/tests.rs)
- [`guest_clock_fixture_cannot_select_an_external_capsule_profile`](src/tests.rs)

## Related documentation

- [Developer test fixtures](../../docs/reference/developer-test-fixtures.md)
- [Native Windows capsule qualification](../../docs/development/native-windows-qualification.md)
- [Windows developer controller implementation](../../docs/development/windows-developer-workflow.md)
- [Local test entry point](../../docs/development/local-tests.md)
- [Execution security profiles](../../docs/runtime/execution-security-profiles.md)
- [Workspace package index](../../crates/README.md)
- [Architecture index](../../ARCHITECTURE.md)
