# latent-oci

Bounded OCI distribution of exact package bytes and detached signature/provenance evidence. The concrete HTTP registry client owns explicitly approved endpoints, authentication scope, resolution, transfers, cache state and upload cleanup.

Registry authorization establishes permission to transfer bytes. Publisher trust, package semantic validity, tenant publication authority and native loading remain independent decisions.

## Responsibilities and architecture

| Source | Responsibility |
| --- | --- |
| [src/lib.rs](src/lib.rs) | OCI reference/descriptor, registry/mapper ports and concrete transport exports. |
| [src/manifest.rs](src/manifest.rs) | Exact OCI manifest byte representation. |
| [src/http/mod.rs](src/http/mod.rs) | Configured HTTP registry client and finite transfer/retention ownership. |
| [src/http/cache.rs](src/http/cache.rs) | Raw transfer cache that cannot replace remote authorization or package assembly. |
| [src/http/upload_worker.rs](src/http/upload_worker.rs) | Supervised bounded upload initiator and reserved cleanup slots. |
| [src/upload.rs](src/upload.rs) | Explicit OciPushRequest and upload association. |

## Execution and ownership

1. Parse a bounded reference under an explicitly configured registry/transport profile.
2. Check endpoint and credential/challenge scope before transfer, using finite resolution, body and deadline limits.
3. Verify received byte identities and detached-evidence association; pass a complete checked bundle to the separate packaging/admission path.
4. Retain upload-session and response ownership through completion or cleanup. Shutdown must retire actual work rather than only drop a caller wait.

## Integration boundaries

Authenticated read replay is restricted to the approved bodyless operations; it is not permission to replay uploads after uncertainty. A cache locator does not authorize access. Advanced endpoint/TLS/bearer settings must match the reviewed transport profile instead of broadening registry authority implicitly.

## Dependencies and build

Direct workspace dependencies: [latent-core](../latent-core/README.md), [latent-artifacts](../latent-artifacts/README.md), [latent-network](../latent-network/README.md).

Consumers with normal workspace dependency edges include [latent](../../apps/latent/README.md). Optional features still gate the selected graph; target-specific and test edges are also declared in the manifests.

Use [Cargo.toml](Cargo.toml) for external dependencies, target gates and test/build edges; [the workspace manifest](../../Cargo.toml) and [the toolchain guide](../../docs/development/toolchain.md) own current pins. Dependency presence does not install a runtime service.

## Tests and verification

The [package entry point](src/lib.rs) and the module links above are the source map. [The workspace package guide](../../docs/development/workspace-packages.md) explains feature/target selection, generated inputs and the registered test workflow.

Inspect a registered suite from the repository root without building or running it:

```sh
python3 tools/test.py explain --suite latent-oci.lib.latent-oci
```

Use `list --output json` to find the remaining package targets. Follow the suite's recipe, platform and prerequisites for preparation, discovery and execution; a registration or compile-only check is not a passing execution/qualification result.

Representative source tests (not a complete coverage inventory):

- [`exact_approved_challenge_is_accepted`](src/http/auth.rs)
- [`realm_service_scope_and_duplicate_fields_fail_closed`](src/http/auth.rs)
- [`token_body_is_bounded_unambiguous_and_scope_bound`](src/http/auth.rs)
- [`bearer_authority_requires_https_and_bounded_explicit_resolution`](src/http/auth.rs)

Integration targets: [tests/http_cache.rs](tests/http_cache.rs), [tests/http_pull.rs](tests/http_pull.rs), [tests/http_transport.rs](tests/http_transport.rs), [tests/registry.rs](tests/registry.rs), [tests/sbom_signature.rs](tests/sbom_signature.rs).

## Related documentation

- [Bounded OCI registry adapter](../../docs/reference/oci-registry.md)
- [Bounded OCI DNS and content redirects](../../docs/reference/oci-network-profile.md)
- [Bounded OCI Bearer authentication](../../docs/reference/oci-bearer-read-auth.md)
- [ADR-0021: Bound registry authority and transfer ownership](../../adr/0021-bound-registry-authority-and-transfer-ownership.md)
- [ADR-0029: Separate registry authority from transport profile](../../adr/0029-separate-registry-authority-from-transport-profile.md)
- [Workspace package index](../README.md)
- [Architecture index](../../ARCHITECTURE.md)
