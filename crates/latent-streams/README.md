# latent-streams

Bounded outbound TCP/TLS stream implementation for explicit qualification. It owns exact destination configuration, socket/chunk lifetimes, current provider epochs and finite maintenance. General production enablement remains gated by the outbound-stream decision and qualification record.

An ordinary HTTP method/path grant cannot authorize opaque socket bytes. The stream provider requires its own exact endpoint and operation authority.

## Responsibilities and architecture

| Source | Responsibility |
| --- | --- |
| [src/config.rs](src/config.rs) | Explicit stream destinations, DNS/static resolution, TLS configuration and limits. |
| [src/provider.rs](src/provider.rs) | Broker-facing StreamProvider and checked operation execution. |
| [src/connection.rs](src/connection.rs) | Affine connection ownership shared safely with pending readiness handles. |
| [src/transport.rs](src/transport.rs) | Physical TCP/TLS owner without locks across external readiness awaits. |
| [src/lifecycle.rs](src/lifecycle.rs) | Stable invoker over explicitly replaced provider epochs. |
| [src/maintenance.rs](src/maintenance.rs) | Bounded node-owned maintenance future without per-connection tasks. |
| [src/tls.rs](src/tls.rs) | Direct TLS with protected explicit trust roots. |

## Execution and ownership

1. Select the qualification feature/profile and install exact stream endpoint/TLS/pool constraints.
2. Accept a broker-approved operation and reserve connection/buffer capacity before DNS or contact.
3. Recheck current authority before physical syscalls after waits; retain accepted I/O and chunks under original ownership.
4. Drain/retire provider epochs and actual sockets before refunding capacity or reporting shutdown.

## Integration boundaries

`development-outbound` is a deliberate feature boundary, not permission to enable streams in every deployment. Unsupported TLS modes must reject rather than fall back to plaintext. No listening socket, permanent application runtime or provider credential discovery is created. Finite maintenance is shared node work and does not retain a guest Store.

## Dependencies and build

Direct workspace dependencies: [latent-core](../latent-core/README.md), [latent-network](../latent-network/README.md), [latent-capabilities](../latent-capabilities/README.md), [latent-policy](../latent-policy/README.md), [latent-protected-files](../latent-protected-files/README.md).

Consumers with normal workspace dependency edges include [latentd](../../apps/latentd/README.md). Optional features still gate the selected graph; target-specific and test edges are also declared in the manifests.

Cargo features (the manifest owns their exact expansion):

| Feature | Enables |
| --- | --- |
| `default` | No additional feature dependency. |
| `development-outbound` | No additional feature dependency. |

Use [Cargo.toml](Cargo.toml) for external dependencies, target gates and test/build edges; [the workspace manifest](../../Cargo.toml) and [the toolchain guide](../../docs/development/toolchain.md) own current pins. Dependency presence does not install a runtime service.

## Tests and verification

The [package entry point](src/lib.rs) and the module links above are the source map. [The workspace package guide](../../docs/development/workspace-packages.md) explains feature/target selection, generated inputs and the registered test workflow.

No package suite is registered in the current suite inventory. Build/type checks and the linked consuming integration/qualification paths establish their own narrower coverage; this is not an implicit test pass.

Representative source tests (not a complete coverage inventory):

- [`opaque_transport_requires_exact_special_address_authority`](src/tests.rs)
- [`unimplemented_host_tls_is_never_silently_replaced_with_tcp`](src/tests.rs)
- [`genuine_http_only_authority_denies_opaque_bytes_before_dns_and_contact`](src/tests/authority.rs)
- [`a_policy_change_while_readable_is_pending_is_checked_before_syscall`](src/tests/currentness.rs)

## Related documentation

- [Bounded standard outbound stream profile v1](../../docs/runtime/outbound-stream-profile.md)
- [Outbound stream implementation and qualification status](../../docs/runtime/outbound-stream-qualification.md)
- [Protected outbound stream administration](../../docs/runtime/outbound-stream-operator.md)
- [Development outbound TCP installation](../../docs/reference/standalone-streams.md)
- [ADR-0059: Defer general outbound streams; evaluate typed protocol boundaries first](../../adr/0059-defer-general-outbound-streams.md)
- [ADR-0061: Bound standard outbound streams beneath language runtimes](../../adr/0061-bound-standard-outbound-streams.md)
- [Workspace package index](../README.md)
- [Architecture index](../../ARCHITECTURE.md)
