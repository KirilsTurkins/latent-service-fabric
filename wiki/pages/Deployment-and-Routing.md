<!-- LSF-WIKI-MANAGED -->
# Deployment and routing

Phase 1 stores immutable releases and durable deployment state, then atomically publishes deterministic revisions and immutable route snapshots. Invocations resolve locally and pin the selected generation. Updates do not mutate an existing activation's pin. Release identity follows the actual component content digest; it is distinct from future OCI package/provenance identities.

Tenant-scoped release/deployment lists use bounded indexed pagination. Tokens are opaque and may expire after mutation or reopen; the CLI does not restart a listing automatically. Tenant-neutral trusted-local records are omitted from scoped release reads.

Apply/delete preconditions compare exact per-object generation: omitted is unconditional, zero requires absence, positive compares the live version. Zero allows Apply only when absent; Delete of an absent object remains not-found. Checks occur at commit. Transport failure after submission can leave an outcome unknown; clients retain commit evidence and never invent a receipt.

Weighted selection and atomic local publication are delivered foundations. Canary orchestration, rollout controllers and automatic rollback are Phase 2. Artifact prefetch, remote watches, clustered placement and separate control-plane availability semantics are later. Shared application HTTP ingress, including bounded Angular SSR/hydration support, is Phase 3; the current loopback RPC endpoint is not that ingress surface.

Authorities: [deployment/routing](https://github.com/KirilsTurkins/latent-service-fabric/blob/release/docs/deployment-routing.md), [release catalog](https://github.com/KirilsTurkins/latent-service-fabric/blob/release/docs/development/local-release-catalog.md), [management](https://github.com/KirilsTurkins/latent-service-fabric/blob/release/docs/reference/management-services.md), [versioning](https://github.com/KirilsTurkins/latent-service-fabric/blob/release/docs/architecture/versioning-and-deployment.md).
