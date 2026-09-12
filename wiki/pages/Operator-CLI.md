<!-- LSF-WIKI-MANAGED -->
# Operator CLI

`latent` performs local package work and acts as a separate authenticated node client. It does not execute a guest inside the CLI. Explicit profiles, finite deadlines, bounded files and stable JSON output support operator-controlled workflows.

| Commands | Delivered behavior |
| --- | --- |
| `package build / inspect / verify` | Deterministic package construction, checked summaries and explicit policy/evidence verification. |
| `package push / pull` | Exact portable packages and detached evidence through an explicit TLS registry profile. |
| `release publish-package / lifecycle / operation` | Authenticated managed publication, historical lifecycle status and retained operation lookup. |
| `release revoke / retire / renew-evidence` | Explicit lifecycle transitions or exact-package evidence renewal with generation preconditions. |
| `deployment apply / get / list / delete / operation` | Managed Apply/Delete, coherent operation snapshots, bounded reads and exact receipt lookup. |
| `rollout start / get / list / operation` | Durable rollout plans, current status and retained operations. |
| `rollout pause / resume / abort / advance` | Explicit manual transitions; policy rows cannot bypass promotion through Advance. |
| `rollout evaluate / promote / rollback` | Diagnostic canary assessment, sealed policy-gated promotion and eligible recorded-target restoration. |
| `audit query` | Explicit scoped pages of durable attempts, outcomes and bounded diagnostics. |
| Invoke, activation, route and node commands | Generic calls, status/cancel, selected routes and bounded node inventory. |

Global `--output json` selects the envelope. Package build/pull use `--output-dir` for a fresh directory, avoiding a collision with that global option. The CLI caps aggregate package layer bytes at 32 MiB and each layer at 16 MiB; detached evidence has a separate 16 MiB ceiling. Node request limits apply independently, so a locally valid package can still exceed its publication budget. No limit is raised automatically to make it fit.

For example, after provisioning policy and evidence through the documented host APIs:

```bash
latent --output json package inspect ./package
latent --config ./client.json --profile operator --output json release publish-package ./package --evidence ./evidence/index.json --operation-id publish-blue --expected-generation 0
latent --config ./client.json --profile operator --output json deployment get blue --operation-snapshot
```

Use the returned snapshot's catalog state version and object generation for managed Apply/Delete. An operation ID is bound to the actor, tenant and exact normalized request. Exact retained replay precedes compare-and-swap; a changed request under the same ID is rejected. Legacy absent-operation behavior remains explicit compatibility, not the managed recovery protocol.

Rollout Start requires the candidate manifest's initial route weight to match the first declared stage. Read the rollback target from GetRollout status after Start; the Start receipt does not contain the resolved rollback target. Use the current rollout revision for changes. Successful rollback creates a new route generation and records the resolved target in its receipt.

A timeout or disconnect is not permission to retry a mutation with new identity or guessed preconditions. Inspect the original operation. Unknown means the finite ledger cannot establish a retained result; Uncertain means durability/recovery has not established a definite answer. Audit acknowledgement and mutation receipt remain separate fields.

Registry manifests and detached referrers are separate publications, so a failed push can leave a known or uncertain partial result. The CLI reports bounded digest/recovery information and performs no automatic mutation retry or pagination. Credentials, raw error strings and evidence are not echoed as diagnostics.

Signing-key provisioning, live policy updates and arbitrary administrative automation are outside this CLI surface. Six language SDK interfaces are described separately in [SDKs](SDKs).

Authorities: [operator workflows](https://github.com/KirilsTurkins/latent-service-fabric/blob/development/docs/phase-2-operator-workflows.md), [CLI reference](https://github.com/KirilsTurkins/latent-service-fabric/blob/development/docs/reference/operator-cli.md), [management services](https://github.com/KirilsTurkins/latent-service-fabric/blob/development/docs/reference/management-services.md).
