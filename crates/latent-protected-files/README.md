# latent-protected-files

Protected host file and directory primitives used by secrets, credentials and durable state roots. On Linux x86-64, reads and rooted mutations use retained descriptors, no-follow path traversal, ownership/mode/type/link checks and bounded before/after observations.

`Secret` and `Integrity` policies have different disclosure requirements. The non-Linux compatibility reader is not equivalent to the external-capsule protected-file profile; execution-profile markers reject unsupported platforms.

## Responsibilities and architecture

| Source | Responsibility |
| --- | --- |
| [src/lib.rs](src/lib.rs) | Bounded read policy and execution-profile marker creation/checking. |
| [src/rooted.rs](src/rooted.rs) | ProtectedRoot, ProtectedMutableFile and descriptor-anchored file operations. |
| [src/rooted/](src/rooted/) | Tests for rooted operations and retained root/file ownership. |

## Execution and ownership

1. The trusted host explicitly selects a path/root and security purpose.
2. Walk ancestors and open descendants through retained descriptors, rejecting symlinks and unsafe ownership, permissions or file kinds.
3. Bound bytes before allocation and check identity/metadata around reads; an observed replacement or mutation fails.
4. Keep the actual root/file owner through storage operations. Recovery output creation refuses unsafe names and accidental overwrite.

## Integration boundaries

Protected paths are host configuration, never guest-selected filesystem authority. A marker is deployment evidence rather than an authentication token. Do not generalize every accepted mode to a blanket 0600 rule: private ancestors and the selected policy affect the checks. Callers still own durability, authorization and blocking-worker placement.

## Dependencies and build

Direct workspace dependencies: [latent-core](../latent-core/README.md).

Consumers with normal workspace dependency edges include [latentd](../../apps/latentd/README.md), [latent-secrets](../latent-secrets/README.md), [latent-streams](../latent-streams/README.md), [latent-state](../latent-state/README.md). Optional features still gate the selected graph; target-specific and test edges are also declared in the manifests.

Use [Cargo.toml](Cargo.toml) for external dependencies, target gates and test/build edges; [the workspace manifest](../../Cargo.toml) and [the toolchain guide](../../docs/development/toolchain.md) own current pins. Dependency presence does not install a runtime service.

## Tests and verification

The [package entry point](src/lib.rs) and the module links above are the source map. [The workspace package guide](../../docs/development/workspace-packages.md) explains feature/target selection, generated inputs and the registered test workflow.

Inspect a registered suite from the repository root without building or running it:

```sh
python3 tools/test.py explain --suite latent-protected-files.lib.latent-protected-files
```

Use `list --output json` to find the remaining package targets. Follow the suite's recipe, platform and prerequisites for preparation, discovery and execution; a registration or compile-only check is not a passing execution/qualification result.

Representative source tests (not a complete coverage inventory):

- [`rooted_reads_reject_unbounded_names_types_links_and_sizes`](src/rooted/tests.rs)
- [`replacement_and_removal_during_read_never_return_old_bytes`](src/rooted/tests.rs)
- [`retained_root_rejects_ancestor_replacement_and_permission_changes`](src/rooted/tests.rs)
- [`content_or_permission_change_after_open_is_rejected`](src/rooted/tests.rs)

## Related documentation

- [Protected standalone configuration files](../../docs/runtime/protected-configuration.md)
- [Protected mutable state files](../../docs/development/protected-state-root.md)
- [Protected local secrets](../../docs/runtime/local-secrets.md)
- [Execution security profiles](../../docs/runtime/execution-security-profiles.md)
- [Workspace package index](../README.md)
- [Architecture index](../../ARCHITECTURE.md)
