<!-- LSF-WIKI-MANAGED -->
# SDKs and generated clients

The repository maintains Rust, Go, TypeScript, Java, .NET and C interface surfaces with executable fixtures. They describe bounded requests/results, identity, cancellation and value behavior. They do not yet bundle production network transports, complete serializers or retry engines.

The operator CLI has a real generated Rust gRPC transport for the delivered node API, including Phase 2 management. That implementation does not imply equivalent generated management transports in all six SDKs.

| Boundary | Meaning |
| --- | --- |
| Invocation identity | Caller/server activation IDs are correlation and status identities, not general side-effect transaction keys. |
| Cancellation | A cancellation request and completed resource cleanup are separate events. |
| Values | Current typed scalar/composite WIT boundaries must validate before execution. |
| C ownership | Borrow scopes and release obligations remain explicit across the ABI. |
| Management versions | Object, route, state, lifecycle and rollout versions are not interchangeable. |
| Retry behavior | Applications inspect exact operation outcomes; no automatic mutation retry is promised. |

Phase 3 plans guest bindings/helpers, six-language parity, a concrete Rust client transport and TypeScript Node transport/browser-safe application integration. See [SDK parity #227](https://github.com/KirilsTurkins/latent-service-fabric/issues/227), [Rust transport #228](https://github.com/KirilsTurkins/latent-service-fabric/issues/228) and [TypeScript transport #230](https://github.com/KirilsTurkins/latent-service-fabric/issues/230). Browser examples must not expose privileged management credentials.

Use [Operator CLI](Operator-CLI) for current executable operator workflows. Keep future provider interfaces aligned with the versioned Phase 3 host ABI rather than assuming ambient network, secrets or filesystem imports.

Authorities: [SDK guide](https://github.com/KirilsTurkins/latent-service-fabric/blob/development/sdk/README.md), [WIT values](https://github.com/KirilsTurkins/latent-service-fabric/blob/development/docs/protocol/wit-values.md), [operator workflows](https://github.com/KirilsTurkins/latent-service-fabric/blob/development/docs/phase-2-operator-workflows.md).
