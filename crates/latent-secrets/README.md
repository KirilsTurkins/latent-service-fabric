# latent-secrets

Linux operator-owned local secret generations and explicitly granted guest disclosure. A configured secret may originate from a protected file or bounded initial process environment. Provider authentication bindings retain opaque credential ownership separately from plaintext guest reads.

Secret installation is trusted host composition. A guest name, configuration epoch or copied reference cannot select arbitrary environment variables/files or reconstruct an old generation.

## Responsibilities and architecture

| Source | Responsibility |
| --- | --- |
| [src/config.rs](src/config.rs) | SecretSpec, source/purpose and finite limits. |
| [src/environment.rs](src/environment.rs) | Bounded capture of the kernel initial environment before allocating arbitrary values. |
| [src/store.rs](src/store.rs) | LocalSecretStore generations, protected sources and explicit credential/disclosure ownership. |
| [src/store/credential_generation.rs](src/store/credential_generation.rs) | Original credential generation retained through provider installation. |
| [src/provider.rs](src/provider.rs) | LocalSecretProvider and its checked broker operation. |

## Execution and ownership

1. The operator installs a bounded exact secret source and purpose through protected configuration.
2. The store captures an owned generation and separates provider-only credentials from disclosable values.
3. A broker-approved activation read intersects current secret generation and policy before exposing bounded bytes.
4. Retire original owners and zeroizing buffers at actual destruction; revocation denies later disclosure without claiming to erase copies already made by a guest.

## Integration boundaries

The implementation/configuration exports are Linux x86-64 gated; a portable build is not local-secret qualification. Provider credentials must not leak through guest reads, Debug text or error messages. Source refresh/currentness and activation memory accounting remain distinct from merely caching a plaintext value.

## Dependencies and build

Direct workspace dependencies: [latent-core](../latent-core/README.md), [latent-capabilities](../latent-capabilities/README.md), [latent-policy](../latent-policy/README.md), [latent-protected-files](../latent-protected-files/README.md).

Consumers with normal workspace dependency edges include [latentd](../../apps/latentd/README.md). Optional features still gate the selected graph; target-specific and test edges are also declared in the manifests.

Use [Cargo.toml](Cargo.toml) for external dependencies, target gates and test/build edges; [the workspace manifest](../../Cargo.toml) and [the toolchain guide](../../docs/development/toolchain.md) own current pins. Dependency presence does not install a runtime service.

## Tests and verification

The [package entry point](src/lib.rs) and the module links above are the source map. [The workspace package guide](../../docs/development/workspace-packages.md) explains feature/target selection, generated inputs and the registered test workflow.

Inspect a registered suite from the repository root without building or running it:

```sh
python3 tools/test.py explain --suite latent-secrets.lib.latent-secrets
```

Use `list --output json` to find the remaining package targets. Follow the suite's recipe, platform and prerequisites for preparation, discovery and execution; a registration or compile-only check is not a passing execution/qualification result.

## Related documentation

- [Protected local secrets](../../docs/runtime/local-secrets.md)
- [Protected standalone configuration files](../../docs/runtime/protected-configuration.md)
- [Configure standalone providers](../../docs/reference/standalone-providers.md)
- [Exercise provider integration from source](../../docs/development/provider-source-walkthrough.md)
- [Workspace package index](../README.md)
- [Architecture index](../../ARCHITECTURE.md)
