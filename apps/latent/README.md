# latent

Standalone operator CLI. It performs explicit bounded local preparation or one selected RPC/registry operation, emits one bounded result and preserves recovery identities. Packaging, verification and shell completion generation have local paths; invocation and management use the configured client identity.

It is an operator client, not a node or guest runtime. A successful transport response, a known durable operation outcome and an audit acknowledgement are represented separately.

## Responsibilities and architecture

| Source | Responsibility |
| --- | --- |
| [src/args.rs](src/args.rs) | Clap command grammar, explicit operation selection and validation. |
| [src/config.rs](src/config.rs) | Bounded credential profiles with redacted secret ownership. |
| [src/command.rs](src/command.rs) | Local preflight, command execution and process exit behavior. |
| [src/client.rs](src/client.rs) | One channel/call under the original monotonic allowance. |
| [src/management.rs](src/management.rs) | Catalog/policy/rollout/transaction/dispatcher management and response association. |
| [src/invocation.rs](src/invocation.rs) | Invoke, retained status and explicit cancellation. |
| [src/package.rs](src/package.rs) | Bounded local package/signature operations and explicitly owned registry transfer. |
| [src/output.rs](src/output.rs) | Stable bounded escaped output, preserving full-width numeric facts. |
| [src/completions.rs](src/completions.rs) | Ahead-of-time shell sources derived from the same grammar without runtime discovery. |

## Execution and ownership

1. Parse the explicit command and bound files/stdin/config before network work.
2. Prepare an immutable operation with exact IDs, preconditions, request limits and original deadline.
3. Execute the selected local action or one RPC/registry operation; no hidden polling or general automatic replay follows uncertain results.
4. Validate/associate the response and emit bounded human/JSON output. Recovery retains original operation identities rather than inventing another mutation.

## Integration boundaries

Completion generation does not load credentials, contact a node or spawn helpers. Transaction retry requires a server-confirmed original disposition, not a gRPC status or dropped future. Registry authority, node credentials and provider credentials are distinct. Use the maintained operator reference for the complete grammar instead of treating module names as stable subcommands.

## Dependencies and build

Direct workspace dependencies: [latent-activation](../../crates/latent-activation/README.md), [latent-artifacts](../../crates/latent-artifacts/README.md), [latent-control-store](../../crates/latent-control-store/README.md), [latent-core](../../crates/latent-core/README.md), [latent-manifest](../../crates/latent-manifest/README.md), [latent-packaging](../../crates/latent-packaging/README.md), [latent-policy](../../crates/latent-policy/README.md), [latent-oci](../../crates/latent-oci/README.md), [latent-rpc](../../crates/latent-rpc/README.md), [latent-signing](../../crates/latent-signing/README.md), [latent-wire](../../crates/latent-wire/README.md).

Use [Cargo.toml](Cargo.toml) for external dependencies, target gates and test/build edges; [the workspace manifest](../../Cargo.toml) and [the toolchain guide](../../docs/development/toolchain.md) own current pins. Dependency presence does not install a runtime service.

## Tests and verification

The [package entry point](src/lib.rs) and the module links above are the source map. [The workspace package guide](../../docs/development/workspace-packages.md) explains feature/target selection, generated inputs and the registered test workflow.

Inspect a registered suite from the repository root without building or running it:

```sh
python3 tools/test.py explain --suite latent.lib.latent
```

Use `list --output json` to find the remaining package targets. Follow the suite's recipe, platform and prerequisites for preparation, discovery and execution; a registration or compile-only check is not a passing execution/qualification result.

Representative source tests (not a complete coverage inventory):

- [`package_output_directory_and_global_output_format_have_distinct_ids`](src/args/package.rs)
- [`transaction_manifest_profile_requires_explicit_operator_selection`](src/args/tests.rs)
- [`activation_tree_has_one_bounded_page_without_cancellation_authority`](src/args/tests.rs)
- [`grammar_has_consistent_leaf_help_and_local_validation_needs_no_profile`](src/args/tests.rs)

Integration targets: [tests/completions.rs](tests/completions.rs), [tests/phase1_conformance.rs](tests/phase1_conformance.rs), [tests/standalone_cli.rs](tests/standalone_cli.rs).

## Related documentation

- [Operator CLI](../../docs/reference/operator-cli.md)
- [Standalone management services](../../docs/reference/management-services.md)
- [Transaction clients](../../docs/development/transaction-clients.md)
- [Bounded OCI registry adapter](../../docs/reference/oci-registry.md)
- [Immutable target inspection](../../docs/reference/target-inspection.md)
- [Local test entry point](../../docs/development/local-tests.md)
- [Workspace package index](../../crates/README.md)
- [Architecture index](../../ARCHITECTURE.md)
