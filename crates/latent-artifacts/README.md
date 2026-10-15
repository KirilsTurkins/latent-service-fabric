# latent-artifacts

Package/content identities, a bounded directory artifact repository, publication lifecycle and reusable raw/preparation inputs. The crate distinguishes immutable component bytes from the tenant/service publication association that permits their use. It supports executable capsules and componentless web publications through distinct checked metadata paths.

Storage integrity, admission evidence and current release eligibility remain separate. Possessing a digest, cache entry or historical receipt does not authorize another activation.

## Responsibilities and architecture

| Source | Responsibility |
| --- | --- |
| [src/package/mod.rs](src/package/mod.rs) | Closed package format, layer roles, content digests and bounded codecs. |
| [src/local_repository/mod.rs](src/local_repository/mod.rs) | DirectoryArtifactRepository, bounded indexes, recovery, publication storage and exact metadata/component reads. |
| [src/admission.rs](src/admission.rs) | Sealed admission authority, upload and recheck ports. |
| [src/lifecycle.rs](src/lifecycle.rs) | Publication/release state, live eligibility, revocation and management preconditions. |
| [src/preparation.rs](src/preparation.rs) | Owned source identity and bounded preparation reads. |
| [src/raw_cache.rs](src/raw_cache.rs) | Finite raw-byte cache, pins, eviction and actual reclamation. |
| [src/web.rs](src/web.rs) | Componentless web artifact/publication metadata and selection contracts. |
| [src/audit.rs](src/audit.rs) | Release mutation audit ownership and reconciliation. |

## Execution and ownership

1. Decode and check exact package bytes; preserve component, package and publication identities independently.
2. An installed admission authority checks evidence and issues a scoped grant. The repository publishes bounded metadata/content under its durable completion protocol.
3. The catalog selects an exact publication. Preparation retains immutable source bytes/metadata and code pins while independently rechecking live eligibility.
4. Release mutations and reclamation obey preconditions, audit and active pins; deleting a logical association does not justify deleting bytes still owned by another publication or reader.

## Integration boundaries

`latent-packaging` assembles supplied bytes; `latent-signing` verifies cryptographic evidence; `latent-policy` owns current supply-chain admission. This crate stores and binds their results rather than combining those decisions into a hash check. `development-test-host` exposes explicit test authority and is not a production trust bypass. Raw caching is not the authenticated Wasmtime native AOT cache.

## Dependencies and build

Direct workspace dependencies: [latent-core](../latent-core/README.md), [latent-audit](../latent-audit/README.md), [latent-contracts](../latent-contracts/README.md), [latent-manifest](../latent-manifest/README.md).

Consumers with normal workspace dependency edges include [latentd](../../apps/latentd/README.md), [latent](../../apps/latent/README.md), [latent-packaging](../latent-packaging/README.md), [latent-oci](../latent-oci/README.md), [latent-signing](../latent-signing/README.md), [latent-policy](../latent-policy/README.md). Optional features still gate the selected graph; target-specific and test edges are also declared in the manifests.

Cargo features (the manifest owns their exact expansion):

| Feature | Enables |
| --- | --- |
| `development-test-host` | No additional feature dependency. |

Use [Cargo.toml](Cargo.toml) for external dependencies, target gates and test/build edges; [the workspace manifest](../../Cargo.toml) and [the toolchain guide](../../docs/development/toolchain.md) own current pins. Dependency presence does not install a runtime service.

## Tests and verification

The [package entry point](src/lib.rs) and the module links above are the source map. [The workspace package guide](../../docs/development/workspace-packages.md) explains feature/target selection, generated inputs and the registered test workflow.

Inspect a registered suite from the repository root without building or running it:

```sh
python3 tools/test.py explain --suite latent-artifacts.lib.latent-artifacts
```

Use `list --output json` to find the remaining package targets. Follow the suite's recipe, platform and prerequisites for preparation, discovery and execution; a registration or compile-only check is not a passing execution/qualification result.

Representative source tests (not a complete coverage inventory):

- [`canonical_digest_matches_fixed_padding_and_chunk_boundary_vectors`](src/content_hash/tests.rs)
- [`local_record_and_receipt_match_shared_schema_fixture`](src/lifecycle/store/schema_tests.rs)
- [`compact_capability_revokes_generation_and_owner_without_store_maps`](src/lifecycle/store/tests.rs)
- [`poisoned_fence_and_unhealthy_owner_are_never_reported_as_retryable_contention`](src/lifecycle/store/tests.rs)

Integration targets: [tests/package_adversarial.rs](tests/package_adversarial.rs), [tests/package_format.rs](tests/package_format.rs), [tests/package_golden.rs](tests/package_golden.rs).

## Related documentation

- [Tenant-scoped publication catalog](../../docs/reference/publication-catalog.md)
- [Publication-bound deployment and execution](../../docs/reference/publication-runtime.md)
- [Authenticated package admission](../../docs/reference/package-admission.md)
- [Release lifecycle and evidence renewal](../../docs/reference/release-lifecycle.md)
- [Bounded raw artifact cache](../../docs/reference/raw-artifact-cache.md)
- [ADR-0027: Separate publication authority from component identity](../../adr/0027-separate-publication-authority-from-component-identity.md)
- [Workspace package index](../README.md)
- [Architecture index](../../ARCHITECTURE.md)
