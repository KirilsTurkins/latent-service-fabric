# latent-vault

Linux x86-64 Vault KV-v2 secret provider using explicit references and bounded shared plaintext ownership. Configuration chooses the endpoint, credential and selected KV field/version; the parser validates the response shape and returns only the approved value.

The whole public implementation is target-gated. An empty successful build on another architecture is not evidence that Vault networking or secret disclosure is supported there.

## Responsibilities and architecture

| Source | Responsibility |
| --- | --- |
| [src/lib.rs](src/lib.rs) | Linux x86-64 target gate and provider/config exports. |
| [src/config.rs](src/config.rs) | VaultConfig, VaultReference, encoding and independent limits. |
| [src/provider.rs](src/provider.rs) | VaultSecretProvider, shared request/cache ownership and disclosure checks. |
| [src/json.rs](src/json.rs) | Duplicate-aware bounded KV-v2 parsing and exact selected-field extraction. |
| [src/memory.rs](src/memory.rs) | Bounded retained plaintext accounting. |

## Execution and ownership

1. Install the explicit protected Vault credential, endpoint and KV-v2 reference through trusted configuration.
2. Use the maintained HTTP/protocol owner with finite transport and response limits.
3. Validate exact field, version, encoding and deletion metadata; dynamic leases or unrelated server data do not become guest values.
4. Disclose only under the activation broker/current policy, retaining plaintext charges through actual owner destruction.

## Integration boundaries

This is not a general Vault API, ambient credential discovery or lease-renewal agent. Local secret ownership, HTTP transport and capability admission remain independent. Errors preserve the safe typed category rather than echoing raw server response bodies or credential material.

## Dependencies and build

There are no unconditional workspace dependencies. Target-specific and test/build edges, if present, are declared in the manifest.

Target-specific workspace edges:

| Target / dependency section | Package |
| --- | --- |
| `cfg(all(target_os = "linux", target_arch = "x86_64")):dependencies` | [latent-core](../latent-core/README.md) |
| `cfg(all(target_os = "linux", target_arch = "x86_64")):dependencies` | [latent-capabilities](../latent-capabilities/README.md) |
| `cfg(all(target_os = "linux", target_arch = "x86_64")):dependencies` | [latent-policy](../latent-policy/README.md) |
| `cfg(all(target_os = "linux", target_arch = "x86_64")):dependencies` | [latent-secrets](../latent-secrets/README.md) |
| `cfg(all(target_os = "linux", target_arch = "x86_64")):dependencies` | [latent-http](../latent-http/README.md) |

Use [Cargo.toml](Cargo.toml) for external dependencies, target gates and test/build edges; [the workspace manifest](../../Cargo.toml) and [the toolchain guide](../../docs/development/toolchain.md) own current pins. Dependency presence does not install a runtime service.

## Tests and verification

The [package entry point](src/lib.rs) and the module links above are the source map. [The workspace package guide](../../docs/development/workspace-packages.md) explains feature/target selection, generated inputs and the registered test workflow.

Inspect a registered suite from the repository root without building or running it:

```sh
python3 tools/test.py explain --suite latent-vault.lib.latent-vault
```

Use `list --output json` to find the remaining package targets. Follow the suite's recipe, platform and prerequisites for preparation, discovery and execution; a registration or compile-only check is not a passing execution/qualification result.

Representative source tests (not a complete coverage inventory):

- [`selected_utf8_binary_exact_version_and_deleted_metadata`](src/json/tests.rs)
- [`no_dynamic_lease_or_raw_server_error_or_nonstring_disclosure`](src/json/tests.rs)
- [`duplicate_depth_collection_and_length_limits_are_enforced`](src/json/tests.rs)

## Related documentation

- [Vault KV-v2 secrets](../../docs/runtime/vault-secrets.md)
- [Protected local secrets](../../docs/runtime/local-secrets.md)
- [Policy-scoped outbound HTTP](../../docs/runtime/outbound-http.md)
- [Shared provider pools](../../docs/runtime/provider-pools.md)
- [Workspace package index](../README.md)
- [Architecture index](../../ARCHITECTURE.md)
