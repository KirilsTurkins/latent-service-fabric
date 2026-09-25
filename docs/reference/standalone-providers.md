# Configure standalone providers

The opt-in `providers` object installs the existing bounded HTTP and immutable
local-blob providers in the standalone node. Explicit `clockMonotonic`, `clockWall`
and `random` installations also enable the maintained activation-clock and
OS-entropy providers. Explicit `secrets` installs the protected local guest-secret
provider. `metrics` shares the node's telemetry exporter, and `localService`
selects a bounded local caller/callee binding. `events` installs the maintained
TLS NATS immediate publisher. Streaming HTTP and S3 have no installation entry
here. The
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

Guest secrets use a separate `secrets` entry with `identity`, a protected
`directory` and one to eight `references`. Each reference contains a public
`reference`, a relative single-file `file` name and optional unsigned
`expiresAtUnixMillis`. Relative directories anchor to the node configuration
file; parent traversal and duplicate reference/file selections are rejected.
Inline values, environment sources and provider-credential purposes are not
accepted. Startup checks private storage and loads file bytes through the
existing local-secret store before readiness. `check-config` never reads them.

Bind `latent:secrets/reader@0.1.0` to the configured service and use the actual
`protected-local-secrets-v1` descriptor in the public provider-binding policy.
Guest disclosure still requires explicit reference-scoped policy and deployment
grants. Files are limited to 4096 bytes, eight references and 32768 reserved
bytes per generation, with at most two retained generations. Expiry uses the
system clock. Values and value digests are excluded from the provider identity.
This entry adds no separate listener, background refresh or ambient credential
discovery. Reload requires explicit node lifecycle management.

Custom metrics use a `metrics` entry containing `identity` and one to sixteen
`descriptors`. Each descriptor declares `name`, `kind` (`counter`,
`up-down-counter`, `gauge` or `histogram`), `unit`, bounded `labels` (each with
`key` and allowed `values`) and `histogramUpperBounds`. The ordinary registry
rejects reserved names, duplicate descriptors/labels/values and nonfinite or
unordered histogram bounds. `check-config` validates this data without starting
an exporter. Bind `latent:telemetry/custom@0.1.0` with the actual
`custom-metrics-v1` provider descriptor and explicit metric-name policies.

The provider shares the node's existing telemetry owner. It adds no exporter
thread or remote destination. Its one configured tenant is limited to 32 series,
128 observations per second and 65536 queued bytes; each activation is limited
to 32 observations, 16 series and 1 MiB of record bytes, further restricted by
its policy and fuel budget. Source identities accept the node's canonical
`revision-v1:sha256:...` values without changing guest metric-name rules.

After provider retirement and exporter shutdown, the bounded stopped report
includes metric attempt/outcome counters, queue bytes, sink loss counters and
up to sixteen captured records containing only exported name, unit and exact
floating-point value bits. Exported names retain the `latent.application.`
prefix. Source/guest labels and other diagnostics are omitted. Truncation and
sink loss are explicit; a finite retained series catalog is not a live exporter.

The optional `localService` entry selects one local deployment through the
existing `lsf-local-service-invocation-v1` dispatcher. It contains `identity`
(whose service is the callee), `deployment` and the callee's exported `contract`.
An explicit consumer binding uses `latent:service/invoke@0.1.0`; its configured
provider service must match the entry. This compiles an `isolated-local` binding
to the exact configured deployment and contract. Self-bindings, foreign binding
tenants, ambiguous provider identities and remote endpoints are rejected.

Only configured consumer services acquire their canonical node-derived service
subjects in tenant admission. Child calls carry service identity without the
operator's administrator claims. The binding compiler verifies the caller ABI,
callee exports, exact publication eligibility and current route; policies and
deployment grants still have to permit the selected callee publication. No
per-capsule worker, listener, VM or persistent guest instance is installed.
Configure a nonzero `maximumChildCalls` and enough cell capacity for parent and
child; delegation remains bounded by the existing depth, descendant and parent
budget rules. Startup does not publish or deploy either component.

An `events` entry contains `identity`, `configuration`, `credentialDirectory`,
`credentialReference` and `credentialFile`. Configuration uses the maintained
`latent_nats::NatsConfig`: one explicit IPv4 peer and TLS server name, approved
roots, one to sixteen exact tenant/topic/subject/stream mappings, a stable
idempotency namespace and finite payload/timeout limits. Every mapping must
belong to the configured tenant. Nonpublic peers require explicit approval;
wildcards, discovered servers and ambient credentials are unavailable.

The protected local-secret store binds token authentication to the exact tenant,
provider ID, TLS server name and port. Neither the token nor its value digest
enters the provider descriptor. Bind `latent:events/publisher@0.2.0` and the
actual `nats-jetstream-publish-v1` descriptor, then grant only approved logical
topics. Installation grants no publish authority. A missing or invalid reply
after a possible publish is `uncertain` and is never automatically replayed.
The existing shared provider pool owns connections and work; shutdown closes
the credential generation and checks that live resource counters are zero.

The node's bounded `ready` record includes actual installed descriptors:
`id`, `tenant`, `service`, `capability`, `profile`, `configurationDigest`, and
decimal-string `configurationEpoch`. Use those exact descriptors when applying
the typed provider-binding policy record; do not manufacture a matching digest.
Installation alone grants no consumer authority. Deployment grants, current
policy, binding restrictions, publication admission, budgets and provider
currentness still apply independently.

Configured bindings are durably established once. Restart requires the exact same
definitions and reattaches live providers without changing catalog bytes,
deployment revisions or route generations. Changed or missing bootstrap
definitions fail closed; this profile does not silently migrate bindings.
Shutdown retires capabilities and reports actual pool, broker, I/O, blob and
retained secret-generation/reference
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
