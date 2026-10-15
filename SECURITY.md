# Security Policy

## Reporting vulnerabilities

Report suspected vulnerabilities through [private vulnerability reporting](https://github.com/KirilsTurkins/latent-service-fabric/security/advisories/new).
Include the affected release or exact commit, operating system/filesystem,
selected security and runtime profiles, a minimal reproduction, and expected
versus observed behavior and impact. Use synthetic data and redact credentials,
private paths and application payloads from configuration and diagnostics.

Keep vulnerability details, signing keys, tokens, raw secret matches and business
snapshots out of public issues, pull requests and artifacts. Suspected credential
exposure requires private reporting and revocation/rotation through its owner;
never test a live credential as proof.

## Version and qualification scope

LSF is an experimental prerelease without production security certification.
Security claims apply to the exact source, host and installed profile being
qualified. Use the versioned guides for [published releases](https://github.com/KirilsTurkins/latent-service-fabric/releases)
and the [Development changes guide](docs/start/development-changes.md) for opt-in
features and remaining acceptance gates. A signed package, recognized ABI,
successful build or passing scan alone does not qualify a runtime or release.

Capsule code and input, request metadata, registry/provider responses, detached
evidence, replaceable caches and native output are untrusted inputs. Validation,
identity and current permission are separate checks. The maintained
[security architecture](docs/architecture/security.md) describes the detailed
controls; this policy summarizes their trust and disclosure boundaries.

## Execution, admission and identity

The trusted computing base includes the node, Wasmtime, approved compiler/native
loader, authentication/catalog/capability hosts, selected provider/renderer/
transport/storage owners and the host OS. Guest Store and logical resource
limits are not whole-process RSS or host-compromise boundaries.

The default `local-experimental-v1` profile is for operator-controlled admission
and preparation. Guest execution uses fresh Stores in fixed in-process cells.
`external-capsule-v1` additionally requires enforced package admission, exact
host compatibility, protected configuration and supported approved isolated
compilation. Startup and `check-config` enforce those requirements; a protected
persisted marker prevents weakening the profile on ordinary restart. Enforced
admission alone does not select compiler isolation. A separate execution-host
profile for containment after guest/provider/renderer-process compromise remains
unsupported. Requested stronger profiles must fail closed rather than downgrade.
See [execution profiles](docs/runtime/execution-security-profiles.md) and
[protected configuration](docs/runtime/protected-configuration.md).

Trusted-local integrity checks do not establish publisher identity. Enforced
[package admission](docs/reference/package-admission.md) combines exact tenant/
package associations, publisher signatures, independently approved builder
provenance, SBOM policy and actual runtime requirements, with durable policy and
clock floors. Compatibility reports and cache hits grant no execution authority.
Both catalog modes use [release lifecycle](docs/reference/release-lifecycle.md)
fences: revocation denies later starts; already accepted work may finish boundedly.
Historical receipts and uncertain persistence cannot establish current permission.

The optional [isolated AOT path](docs/runtime/trusted-aot.md) bounds Linux x86_64
compilation and authenticates persistent native reuse against exact source,
compiler, engine/host and security identities. It accepts no arbitrary external
native artifacts. The parent validator/loader remains trusted; compiler isolation
does not provide a separate guest execution process.

## Transports, providers and application isolation

Management/invocation RPC remains authenticated loopback transport. Trusted
principals and current scoped decisions supply authority, not request-body
identities, correlation IDs or descriptive grants. Cluster mTLS, remote delegation
and distributed authorization leases remain unimplemented.

The optional [shared HTTP/TLS listener](docs/reference/http-ingress.md) maps
explicit public origins to configured low-privilege principals; forwarded headers
and probes never grant identity. The [browser boundary](docs/security/browser-boundary.md)
fixes CSP/CSRF/header and disclosure rules, not arbitrary HTML sanitization,
same-origin script safety or browser end-user authentication. Document navigation,
styles and cross-origin assets need explicit policy. Selected [HTTPS](docs/operations/local-https-edge.md),
[compression](docs/operations/static-compression.md) and [readiness](docs/operations/readiness-probes.md)
adapters also become trusted node-level components.

[Standalone provider configuration](docs/reference/standalone-providers.md)
accepts explicit HTTP/streaming HTTP, local blobs/secrets, context/logging,
clocks, randomness, metrics, local calls and immediate NATS publication. S3 and
Vault use trusted Rust embedding. The [activation-runtime bridge](docs/runtime/activation-runtime.md)
has separate installation, grants and finite ownership; recognizing its ABI does
not qualify a language runtime. [Development TCP streams](docs/reference/standalone-streams.md)
require their build feature and qualification gates; direct host TLS retains its
separate unsupported installation boundary. None supplies ambient guest socket,
filesystem, process or environment access.

The [policy/broker boundary](docs/runtime/capability-policies.md) rechecks current
scope, publication, policy and provider authority. Installation supplies neither
permission nor resource reservation. [Async I/O](docs/runtime/async-host-io.md)
and [provider pools](docs/runtime/provider-pools.md) retain physical-work,
connection, buffer and retired-epoch charges until actual cleanup. Timeout or
waiter loss is not cell-reuse proof; credentials stay out of public observations.

## Protected transactions and recovery

Development's explicitly [installed transaction runtime](docs/development/installed-transaction-rpc.md)
requires protected storage, enforced admission, audit, capability policy, an exact
signed operation companion and current namespace/result/effect authority.
Ordinary stateless deployment does not enable it. The host atomically commits
state, intents, original outcomes and applicable inbox facts; guests cannot
commit early, weaken atomicity or make unsupported irreversible calls inside
strict commands. Result lookup and deferred dispatch have independent current
permissions. Durable intent is not provider acknowledgement or universal
exactly-once external execution.

Timeout, disconnect, cancellation and expired/unknown history are not abort
proof. Recover by the original command/attempt/effect identity under current
authority. [Protected restore](docs/architecture/protected-offline-recovery.md)
keeps original business identities, advances recovery epoch, discards historical
grants and stays paused for explicit reconciliation. The [ADR-0062 identity variance](adr/0062-host-own-serializable-transactions-and-durable-outcomes.md#implementation-status-and-restore-identity)
remains an explicit architectural decision gate. Backups, checkpoints and
restored business data require private custody; fixed container backup roots do
not automatically include a separate external checkpoint. Neither matching file
bytes nor receipt metadata proves fresh storage or physical retirement. Complete
native/application/packaged recovery qualification remains separate.

## Security monitoring and evidence

The [security baseline](docs/development/security-baseline.md) defines RustSec,
resolved SDK advisory inventory, redacted secret scans, source/workflow rules,
expiring exceptions and fail-closed canaries. Its coordinator scopes changed
surfaces and configures weekly/manual scans of both `development` and `release`.
The [monitoring runbook](docs/operations/maintained-security-monitoring.md)
separates configured services from actual executed, source-bound coverage.

A green scan is a bounded observation using its recorded source, tools, advisory
data and selected jobs. It does not prove absence of vulnerabilities, full
semantic authorization analysis, current runtime qualification or release
approval. Old receipts do not qualify later code or dependency graphs. Keep
secret findings redacted and report suspected exposure through the private
channel above.
