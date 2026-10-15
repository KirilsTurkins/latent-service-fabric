# latent-network

Shared address classification and explicit bounded DNS resolution for network providers. It canonicalizes addresses, rejects special/mapped-address policy bypasses and resolves one configured hostname through one selected DNS server with finite answers, cache and waiter ownership.

This crate has no workspace dependencies and grants no HTTP, stream or registry authority. Callers combine its network facts with their own exact endpoint and activation policy.

## Responsibilities and architecture

| Source | Responsibility |
| --- | --- |
| [src/address.rs](src/address.rs) | Canonical addresses, network ranges and explicit special-address policy. |
| [src/dns.rs](src/dns.rs) | Resolver, fixed answer storage, expiry, bounded admission and close/usage observations. |
| [src/dns/decode.rs](src/dns/decode.rs) | Bounded DNS response parsing. |
| [src/dns/exchange.rs](src/dns/exchange.rs) | Owned UDP/TCP exchange with finite framing and deadlines. |

## Execution and ownership

1. Validate the hostname, explicit resolver endpoint, TTL ceiling, address policy and waiter bound.
2. Serve a still-valid cache entry or reserve finite resolver admission; coalesce actual resolution under the original deadline.
3. Use bounded UDP exchange and the same selected TCP resolver for truncation fallback, then validate every returned address.
4. Return actual `valid_until`; callers must not restart the maximum TTL. Close clears cached answers and rejects new work.

## Integration boundaries

There is no ambient system resolver or search-suffix discovery. A broad approved network does not implicitly approve metadata/special destinations. Cache hits still require the caller's capability decision. The observed resolution hook confirms physical allocation against the caller's original native reservation; it does not create a second accounting owner.

## Dependencies and build

There are no unconditional workspace dependencies. Target-specific and test/build edges, if present, are declared in the manifest.

Consumers with normal workspace dependency edges include [latent-oci](../latent-oci/README.md), [latent-http](../latent-http/README.md), [latent-streams](../latent-streams/README.md). Optional features still gate the selected graph; target-specific and test edges are also declared in the manifests.

Use [Cargo.toml](Cargo.toml) for external dependencies, target gates and test/build edges; [the workspace manifest](../../Cargo.toml) and [the toolchain guide](../../docs/development/toolchain.md) own current pins. Dependency presence does not install a runtime service.

## Tests and verification

The [package entry point](src/lib.rs) and the module links above are the source map. [The workspace package guide](../../docs/development/workspace-packages.md) explains feature/target selection, generated inputs and the registered test workflow.

Inspect a registered suite from the repository root without building or running it:

```sh
python3 tools/test.py explain --suite latent-network.lib.latent-network
```

Use `list --output json` to find the remaining package targets. Follow the suite's recipe, platform and prerequisites for preparation, discovery and execution; a registration or compile-only check is not a passing execution/qualification result.

Representative source tests (not a complete coverage inventory):

- [`truncated_udp_uses_only_the_same_explicit_tcp_resolver_and_fixed_cache`](src/dns/tests.rs)
- [`tcp_length_is_rejected_before_unbounded_read_or_allocation`](src/dns/tests.rs)
- [`broad_networks_do_not_authorize_special_or_mapped_metadata_addresses`](src/dns/tests.rs)

## Related documentation

- [Policy-scoped outbound HTTP](../../docs/runtime/outbound-http.md)
- [Bounded standard outbound stream profile v1](../../docs/runtime/outbound-stream-profile.md)
- [Bounded OCI DNS and content redirects](../../docs/reference/oci-network-profile.md)
- [Shared provider pools](../../docs/runtime/provider-pools.md)
- [Workspace package index](../README.md)
- [Architecture index](../../ARCHITECTURE.md)
