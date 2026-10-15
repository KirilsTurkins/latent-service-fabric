# latent-commit

Host-owned atomic command completion across state, durable result, outbox and inbox. `atomic` implements bounded command admission, identity/fingerprint checks, complete-envelope planning, physical attempt ownership and recovery/retention on the shared state engine. The root also retains generic coordination ports.

`model` is a finite deterministic reference model. Its schedules help test the protocol but do not prove filesystem durability, physical cleanup or production authority sealing.

## Responsibilities and architecture

| Source | Responsibility |
| --- | --- |
| [src/lib.rs](src/lib.rs) | Generic activation commit plans, receipts, status and coordination ports. |
| [src/atomic/mod.rs](src/atomic/mod.rs) | Closed command/result identity and complete-envelope API. |
| [src/atomic/writer.rs](src/atomic/writer.rs) | PreparedAdmission, non-cloneable AdmittedCommand, CompleteEnvelope and writer decisions. |
| [src/atomic/captured.rs](src/atomic/captured.rs) | Affine guest state/effect staging and exact original authority capture. |
| [src/atomic/ownership.rs](src/atomic/ownership.rs) | Physical executor/commit/cleanup guards and quarantine. |
| [src/atomic/retention.rs](src/atomic/retention.rs) | Caller-driven bounded retention on the original storage owner. |
| [src/atomic/validation.rs](src/atomic/validation.rs) | Coherent bounded startup validation of linked rows. |
| [src/model/mod.rs](src/model/mod.rs) | Independent protocol reference without engine/provider/clock/RPC implementation. |

## Execution and ownership

1. Compute exact command identity and input fingerprint, then inspect the original namespace/result policy under current admission.
2. Atomically claim a new attempt or return the original durable command/result association; changed fingerprints conflict.
3. Run the admitted guest with affine physical ownership and collect validated state plus captured deferred intents.
4. Prepare and accept one complete batch for state/result/outbox/inbox and accounting. Preserve conflict, known-not-committed and recovery-required dispositions.
5. Retire executor/native owners before a durable abort can justify explicit retry; retain floors/results until the configured recovery/retention contract permits reclamation.

## Integration boundaries

The host commits after validated guest completion; guests cannot call a durable commit directly. Immediate HTTP or synchronous child calls do not become staged effects merely by occurring inside a command. A missing reply, dropped future, elapsed deadline or lease expiry is not abort proof. Production writes borrow the same protected engine worker rather than opening another database or dispatching providers under a writer fence.

## Dependencies and build

Direct workspace dependencies: [latent-core](../latent-core/README.md), [latent-state](../latent-state/README.md), [latent-effects](../latent-effects/README.md).

Consumers with normal workspace dependency edges include [latentd](../../apps/latentd/README.md), [latent-wire](../latent-wire/README.md), [latent-node](../latent-node/README.md). Optional features still gate the selected graph; target-specific and test edges are also declared in the manifests.

Use [Cargo.toml](Cargo.toml) for external dependencies, target gates and test/build edges; [the workspace manifest](../../Cargo.toml) and [the toolchain guide](../../docs/development/toolchain.md) own current pins. Dependency presence does not install a runtime service.

## Tests and verification

The [package entry point](src/lib.rs) and the module links above are the source map. [The workspace package guide](../../docs/development/workspace-packages.md) explains feature/target selection, generated inputs and the registered test workflow.

Inspect a registered suite from the repository root without building or running it:

```sh
python3 tools/test.py explain --suite latent-commit.lib.latent-commit
```

Use `list --output json` to find the remaining package targets. Follow the suite's recipe, platform and prerequisites for preparation, discovery and execution; a registration or compile-only check is not a passing execution/qualification result.

Representative source tests (not a complete coverage inventory):

- [`actual_engine_success_reopens_with_state_result_inbox_and_exact_effect_linkage`](src/atomic/tests.rs)
- [`identical_concurrent_claims_have_one_writer_and_changed_fingerprints_conflict`](src/atomic/tests.rs)
- [`lost_business_rejection_replays_after_restart_and_changed_business_state`](src/atomic/tests.rs)
- [`pre_fence_revocation_and_occ_failure_leave_all_business_families_untouched`](src/atomic/tests.rs)

## Related documentation

- [Activation commit protocol](../../docs/protocol/commit-protocol.md)
- [Atomic command envelope](../../docs/development/atomic-command-envelope.md)
- [Command completion coordinator](../../docs/development/command-completion-coordinator.md)
- [Actual command execution proof](../../docs/development/command-execution-proof.md)
- [Response retention and reserved storage recovery](../../docs/architecture/transaction-retention.md)
- [ADR-0062: Host-own serializable transactions and durable outcomes](../../adr/0062-host-own-serializable-transactions-and-durable-outcomes.md)
- [Workspace package index](../README.md)
- [Architecture index](../../ARCHITECTURE.md)
