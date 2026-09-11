<!-- LSF-WIKI-MANAGED -->
# Security and isolation

The standalone node listens on explicit loopback HTTP endpoints and authenticates bounded configured Bearer credentials. Tenant roles scope releases, deployments and invocation; inventory requires operator authority. This is not a public TLS endpoint or multi-node identity system.

Wasmtime provides the Component Model boundary, fresh stores and budgeted execution. Context, logs and clocks follow disclosure/redaction policy. No ambient WASI filesystem, environment, process or network authority is installed. Unsupported capability/resource dimensions fail instead of silently granting access.

Budget ceilings intersect capsule, deployment, node and request policy: CPU fuel, guest memory, accepted log bytes and monotonic wall/deadline limits. Cancellation acceptance, native interruption and completed cleanup are separate; uncertain cells are quarantined.

Component digests and durable metadata verification are implemented. OCI signatures, provenance/SBOM and trusted AOT distribution are Phase 2. General capability providers are Phase 3; mTLS clustered identity is later. In-process class pools do not implement separate trust-host isolation.

No completion report, benchmark or alpha tag establishes production security certification. Follow the [security policy](https://github.com/KirilsTurkins/latent-service-fabric/blob/release/SECURITY.md).

Authorities: [capabilities](https://github.com/KirilsTurkins/latent-service-fabric/blob/release/docs/runtime/capabilities.md), [standalone node](https://github.com/KirilsTurkins/latent-service-fabric/blob/release/docs/reference/standalone-node.md), [security architecture](https://github.com/KirilsTurkins/latent-service-fabric/blob/release/docs/architecture/security.md).
