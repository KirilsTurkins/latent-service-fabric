<!-- LSF-WIKI-MANAGED -->
# Phase 1 baseline and current delivery map

**Functional completion: September 8, 2026. Performance extension complete: September 11, 2026.** The original functional gate and later optimization/comparison campaigns are separate evidence populations.

| Delivered surface | Behavior and boundary |
| --- | --- |
| Build and manifests | Pinned toolchains, generated bindings and strict bounded manifest codecs. |
| Releases | Immutable digests, verified metadata/components, durable local publication, scoped reads and pagination. |
| Deployments/routes | Atomic durable publication, exact generation preconditions, deterministic revisions and immutable snapshots. |
| Budgets | Admitted ledger for CPU fuel, memory, accepted logs and wall/deadline ceilings; later dimensions rejected. |
| Admission/scheduling | Bounded running/queued capacity, fixed class pools, tenant fairness and explicit cancellation ownership. |
| Wasmtime | Generic Component Model dispatch, bounded preparation cache, fresh Store and canonical scalar/composite values. |
| Capabilities | Context, logs and clocks; no ambient WASI filesystem, environment, process or network access. |
| Lifecycle/RPC | Invoke, retained status and explicit cancel, scoped authority and caller/server IDs. |
| Management | Release, deployment, route and bounded operator node-inventory adapters. |
| Node/CLI | Linux node, explicit loopback credentials, durable restart, bounded shutdown and release-to-invocation workflow. |
| SDKs | Six interface surfaces and executable fixtures; no bundled network transports or retries. |

Original full scale evidence reaches 100,000 releases/deployments with fixed execution topology and growing catalog RSS. Three full mixed soaks, seven benchmark runs and seven controlled historical/current pairs retain their own limits. CI conformance is distinct from those campaigns.

The extension covers artifact recovery, warm acquisition, cold preparation, cache lookup, budgets/disconnect cleanup, request ownership, value codec, engine profiles, catalog memory/mutations and scheduler queues. Some changes regress timing or memory; [performance guidance](Performance-and-Infrastructure) retains those results.

Actual Docker and Kubernetes full comparisons each completed 9,926 offers successfully. [Epic #97](https://github.com/KirilsTurkins/latent-service-fabric/issues/97), [gate #113](https://github.com/KirilsTurkins/latent-service-fabric/issues/113) and [milestone 5](https://github.com/KirilsTurkins/latent-service-fabric/milestone/5) are closed. #110 is closed as not planned. Test-reliability [#132](https://github.com/KirilsTurkins/latent-service-fabric/issues/132) was tracked separately from this extension milestone.

Authorities: [functional completion](https://github.com/KirilsTurkins/latent-service-fabric/blob/development/docs/phase-1-completion.md), [extension report](https://github.com/KirilsTurkins/latent-service-fabric/blob/development/docs/phase-1-extension-completion.md), [roadmap](https://github.com/KirilsTurkins/latent-service-fabric/blob/development/docs/roadmap.md).

## Phase 2 implementation and pending delivery gate

The historical results above are unchanged. Phase 2 extends that baseline with:

| Delivered surface | Boundary |
| --- | --- |
| Portable packages and OCI | Deterministic content, bounded registry transfer, exact detached evidence and storage-only raw caching. |
| Publisher/provenance/SBOM checks | Separate authorized signer roles, exact package/component binding and honest incomplete inventory. |
| Trusted admission and lifecycle | Current policy/clock floors, sealed capabilities, revoke/retire/evidence renewal and historical status. |
| Compatibility and AOT | Structural package analysis, actual runtime profile, isolated approved compilation and protected local native reuse. |
| Audit and operations | Bounded durable attempts/outcomes, atomic managed deployment receipts and exact recovery lookup. |
| Rollout/canary/rollback | Operator commands, complete sealed-window promotion and fresh eligible restoration through a new route generation. |
| Operator CLI | Real package/registry and authenticated node workflows, with explicit preconditions and no hidden mutation retries. |

[Delivery gate #158](https://github.com/KirilsTurkins/latent-service-fabric/issues/158) is pending. The implementation map is not a Phase 2 release or performance receipt. Current guidance is on development until release publication; [Phase 3 has 41 planned tickets](https://github.com/KirilsTurkins/latent-service-fabric/issues/201).

See [operator workflows](https://github.com/KirilsTurkins/latent-service-fabric/blob/development/docs/phase-2-operator-workflows.md), [security](Security-and-Isolation) and [deployment/recovery](Deployment-and-Routing).
