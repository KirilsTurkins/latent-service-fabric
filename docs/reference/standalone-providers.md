# Configure standalone providers

The opt-in `providers` object installs the existing bounded HTTP and immutable
local-blob providers in the standalone node. Explicit `clockMonotonic`, `clockWall`
and `random` installations also enable the maintained activation-clock and
OS-entropy providers. It does not install a guest secret
provider, streaming HTTP, S3, events, or an invented provider profile. The
[configuration schema](../../schemas/node-providers.schema.json) describes the
closed input. This example is the provider section of a protected node file:

```json
{
  "providers": {
    "formatVersion": 1,
    "blob": {
      "identity": {"id": "blob", "tenant": "tests", "service": "blob-host", "epoch": 1},
      "namespace": "workflow"
    },
    "bindings": [
      {"name": "blob-binding", "tenant": "tests", "consumerService": "generic",
       "providerService": "blob-host", "contract": "latent:blob/blob@0.2.0",
       "providerBinding": "blob-installed", "route": "guest-blob"}
    ]
  }
}
```

Each scalar installation takes only `identity` (the same closed fields as the
blob example). The corresponding contracts are `latent:clock/monotonic@0.1.0`,
`latent:clock/wall@0.1.0`, and `latent:random/random@0.1.0`. Installation does not
grant access: an explicit binding, provider-binding policy, capability policy
and deployment grant are still required for each consumer. Clock profiles
charge 100 fuel per call. Entropy uses the existing nonblocking OS provider,
with at most 4096 bytes per call and 65536 per activation; no seeded test source
or fallback entropy can be configured. Registrations are shared node-owned
objects, with no per-service worker, timer, listener or persistent guest heap.

Installation requires Linux x86_64, a protected configuration file, `phase3`
budgets, `capabilityPolicies`, and durable audit. Omission disables installation;
explicit null and unsupported fields fail closed. `check-config` validates the
configuration without installing providers or opening credential/blob storage.
Actual startup separately verifies protected credential storage and may fail.

HTTP configuration is the existing `latent_http::HttpProviderConfig`: explicit
origins, address policy, static or bounded DNS resolution, redirects, roots and
finite request/response/header limits. Credentials are file references under an
explicit protected `credentialDirectory`, relative to the node file if not
absolute. Each reference binds one configured destination, tenant, provider ID
and approved credential header. Secret bytes are neither configuration values
nor public configuration digests, CLI outputs, guest imports, or diagnostics.
The shared workflow writes a clearly public test-only credential, not a real
credential. Production credentials must be supplied by the operator.

The node's bounded `ready` record includes actual installed descriptors:
`id`, `tenant`, `service`, `capability`, `profile`, `configurationDigest`, and
decimal-string `configurationEpoch`. Use those exact descriptors when applying
the typed provider-binding policy record; do not manufacture a matching digest.
Installation alone grants no consumer authority. Deployment grants, current
policy, binding restrictions, publication admission, budgets and provider
currentness still apply independently.

Host bindings are durably established once. Restart requires the exact same
definitions and reattaches live providers without changing catalog bytes,
deployment revisions or route generations. Changed or missing bootstrap
definitions fail closed; this profile does not silently migrate bindings.
Shutdown retires capabilities and reports actual pool, broker, I/O and blob
reclamation counters. A failed or incomplete cleanup is not reported as clean.

Combining the resident rollout worker with capability policy/provider work
requires two bounded control blocking slots, not one. The CLI derives this
fixed node-wide ceiling; embedders can use `NodeSettings::control_blocking_threads`.
Otherwise the rollout worker would occupy the only slot and starve protected
credential reads, blob work and policy operations. This adds no per-service
thread, pool or listener.

## Validate a configured node

Use [the capability guide](../learn/use-capabilities.md) for allowed and denied
operations, and [provider diagnostics](../how-to/operate-capability-providers.md)
when a request fails. The [node reference](standalone-node.md) describes complete
configuration, startup and authenticated management.

The maintained test fixture, exported package format and startup regression
history belong to [the contributor validation reference](../development/standalone-provider-validation.md).
