# latent-identity

Authentication, authorization, delegation and node/workload identity interfaces. The crate defines how trusted adapters present credentials and request an identity or decision; it does not supply a credential verifier, certificate agent or clustered identity service.

Use these ports when an embedding needs interchangeable identity providers. The standalone node's concrete credential and transport checks live in its configured adapters, rather than being created by these traits.

## Responsibilities and architecture

| Source | Responsibility |
| --- | --- |
| [src/lib.rs](src/lib.rs) | PresentedCredential, AuthenticationContext, AuthorizationRequest/Decision, DelegationToken, NodeIdentity and provider traits. |

## Execution and ownership

1. A transport adapter gathers credentials and transport facts without treating request metadata as authenticated claims.
2. An installed Authenticator produces a principal; an Authorizer decides an explicit action/resource request.
3. An installed DelegationIssuer issues/verifies scoped delegation under its own authority and validity policy.
4. NodeIdentityProvider supplies current/rotated workload identity only when a concrete host implementation is installed.

## Integration boundaries

A token byte vector or certificate-chain field is descriptive data, not proof of validation. These interfaces neither install mTLS nor implement publication/capability policy. Tenant isolation and exact standalone endpoint restrictions remain the concrete transport and broker owners' responsibility.

## Dependencies and build

Direct workspace dependencies: [latent-core](../latent-core/README.md).

Consumers with normal workspace dependency edges include [latent-ingress](../latent-ingress/README.md). Optional features still gate the selected graph; target-specific and test edges are also declared in the manifests.

Use [Cargo.toml](Cargo.toml) for external dependencies, target gates and test/build edges; [the workspace manifest](../../Cargo.toml) and [the toolchain guide](../../docs/development/toolchain.md) own current pins. Dependency presence does not install a runtime service.

## Tests and verification

The [package entry point](src/lib.rs) and the module links above are the source map. [The workspace package guide](../../docs/development/workspace-packages.md) explains feature/target selection, generated inputs and the registered test workflow.

Inspect a registered suite from the repository root without building or running it:

```sh
python3 tools/test.py explain --suite latent-identity.lib.latent-identity
```

Use `list --output json` to find the remaining package targets. Follow the suite's recipe, platform and prerequisites for preparation, discovery and execution; a registration or compile-only check is not a passing execution/qualification result.

## Related documentation

- [Identity and capability architecture](../../docs/architecture/identity-and-capabilities.md)
- [Standalone node](../../docs/reference/standalone-node.md)
- [Cluster topology](../../docs/architecture/cluster-topology.md)
- [Security architecture](../../docs/architecture/security.md)
- [Workspace package index](../README.md)
- [Architecture index](../../ARCHITECTURE.md)
