<!-- LSF-WIKI-MANAGED -->
# Getting started

Use the product repository's current development branch for Phase 2. This Wiki checkout is documentation source and contains an older code snapshot; never build or merge its product files into a release.

The supported standalone path uses Linux and the pinned repository toolchain. Begin with the [toolchain](https://github.com/KirilsTurkins/latent-service-fabric/blob/development/docs/development/toolchain.md), [build foundation](https://github.com/KirilsTurkins/latent-service-fabric/blob/development/docs/development/build-foundation.md) and [standalone quickstart](https://github.com/KirilsTurkins/latent-service-fabric/blob/development/docs/development/standalone-quickstart.md). `make help` lists ordinary checks and explicit heavy/manual targets.

A small local path is:

1. Build the maintained echo capsule with `make echo-capsule`.
2. Configure a node and a separate client profile with explicit loopback credentials.
3. Publish a validated release, apply its deployment, inspect the route and invoke its WIT export.
4. Inspect status and accounting; stop the node through its owned shutdown path.

For the Phase 2 supply chain, follow the [operator workflow guide](https://github.com/KirilsTurkins/latent-service-fabric/blob/development/docs/phase-2-operator-workflows.md). It covers package build/inspect, explicit registry profiles, exact evidence files, offline verification and authenticated managed publication. Publisher/builder signing and key provisioning use host APIs; the CLI does not invent authority from caller metadata.

Choose the node mode deliberately. Omitted supply-chain settings retain trusted-local compatibility. Enforced mode reads a bounded policy file and requires publisher, provenance and configured SBOM checks. An initialized enforced catalog refuses downgrade. Audit, manual rollouts and isolated AOT are separately configured bounded owners.

Registry and client credentials use separate files. Package output directories are fresh explicit destinations. Mutation commands require operation identities and current preconditions; read them from the relevant status or operation snapshot rather than guessing or silently retrying.

The maintained [real workflow runner](https://github.com/KirilsTurkins/latent-service-fabric/blob/development/tools/run_phase2_operator_workflow.py) exercises separate CLI/node processes and a TLS registry with temporary fixtures. It is a validation scenario, not a production provisioning system.

Phase 2 delivery gate [#158](https://github.com/KirilsTurkins/latent-service-fabric/issues/158) remains pending. General application HTTP ingress and provider capabilities are Phase 3 work.
