# latent-policy

Two concrete authority owners: bounded tenant capability policy and supply-chain package admission. Both distinguish descriptive configuration/reports from sealed current decisions. Capability rules control which installed operation an activation may request; supply-chain rules control which exact publication may become executable or serve web content.

These owners retain bounded generations and currentness fences. Cached plans, uploaded receipts and historical approvals cannot reconstruct a live grant.

## Responsibilities and architecture

| Source | Responsibility |
| --- | --- |
| [src/capability.rs](src/capability.rs) | Bounded policy vocabulary and tenant-scoped authorization owner. |
| [src/capability/control.rs](src/capability/control.rs) | Finite policy management jobs on an existing control runtime. |
| [src/capability/store/authority/owned.rs](src/capability/store/authority/owned.rs) | Owned current policy captures for fixed-worker activation contexts. |
| [src/supply_chain.rs](src/supply_chain.rs) | SupplyChainAuthority, independent acceptance fence and durable policy/time floor. |
| [src/supply_chain/ledger.rs](src/supply_chain/ledger.rs) | Atomically replaced durable floor with bounded staging. |
| [src/supply_chain/verification.rs](src/supply_chain/verification.rs) | Shared diagnostic evidence evaluation, separate from admission-grant construction. |

## Execution and ownership

1. Install explicit bounded operator policy and trusted clock/runtime requirements.
2. Evaluate exact package evidence or activation operation scope against the appropriate owner.
3. Retain captured policy/publication identity and recheck currentness at the final acceptance fence.
4. Persist required durable generations/floors before adoption; retirement or revocation cannot be undone by replaying an old report.

## Integration boundaries

No provider I/O belongs inside authority fences. A policy record does not create a per-deployment thread/listener. Supply-chain verification has a finite admission slot rather than an unbounded queue. `development-test-host` is an explicit fixture configuration, while ordinary node composition requires the actual current authority owners.

## Dependencies and build

Direct workspace dependencies: [latent-core](../latent-core/README.md), [latent-manifest](../latent-manifest/README.md), [latent-artifacts](../latent-artifacts/README.md), [latent-packaging](../latent-packaging/README.md), [latent-signing](../latent-signing/README.md).

Consumers with normal workspace dependency edges include [latentd](../../apps/latentd/README.md), [latent](../../apps/latent/README.md), [latent-wasmtime](../latent-wasmtime/README.md), [latent-capabilities](../latent-capabilities/README.md), [latent-secrets](../latent-secrets/README.md), [latent-http](../latent-http/README.md). Optional features still gate the selected graph; target-specific and test edges are also declared in the manifests.

Cargo features (the manifest owns their exact expansion):

| Feature | Enables |
| --- | --- |
| `development-test-host` | `latent-artifacts/development-test-host` |

Use [Cargo.toml](Cargo.toml) for external dependencies, target gates and test/build edges; [the workspace manifest](../../Cargo.toml) and [the toolchain guide](../../docs/development/toolchain.md) own current pins. Dependency presence does not install a runtime service.

## Tests and verification

The [package entry point](src/lib.rs) and the module links above are the source map. [The workspace package guide](../../docs/development/workspace-packages.md) explains feature/target selection, generated inputs and the registered test workflow.

Inspect a registered suite from the repository root without building or running it:

```sh
python3 tools/test.py explain --suite latent-policy.lib.latent-policy
```

Use `list --output json` to find the remaining package targets. Follow the suite's recipe, platform and prerequisites for preparation, discovery and execution; a registration or compile-only check is not a passing execution/qualification result.

Representative source tests (not a complete coverage inventory):

- [`cancelled_waiter_keeps_queued_or_running_work_charged_until_actual_completion`](src/capability/control/tests.rs)
- [`shutdown_timeout_reports_owned_work_and_rejects_new_submissions`](src/capability/control/tests.rs)
- [`endpoint_scope_is_exact_and_cannot_be_derived_from_http_authority`](src/capability/resources.rs)
- [`malformed_ambiguous_and_wildcard_endpoints_fail_closed`](src/capability/resources.rs)

## Related documentation

- [Durable capability policies](../../docs/runtime/capability-policies.md)
- [Sealed activation capability broker](../../docs/runtime/capability-broker.md)
- [Authenticated package admission](../../docs/reference/package-admission.md)
- [Package publisher signatures and current trust](../../docs/reference/publisher-trust.md)
- [Execution security profiles](../../docs/runtime/execution-security-profiles.md)
- [Workspace package index](../README.md)
- [Architecture index](../../ARCHITECTURE.md)
