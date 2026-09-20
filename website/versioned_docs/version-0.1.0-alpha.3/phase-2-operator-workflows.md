# Phase 2 operator workflows

The `latent` CLI packages local bytes, transfers immutable packages and detached
evidence through OCI, checks an explicit local verification policy, and manages
releases, deployments and rollouts through authenticated RPCs. A local client
path is never interpreted as a node catalog path. The node independently checks
its current policy, release lifecycle and runtime requirements.

## Local packages and evidence

```sh
latent package build --source package-source.json --input-root build-inputs --output-dir package --sbom-inputs sbom-inputs.json
latent package inspect package --output json
latent package verify package --evidence-index evidence/index.json --evidence-root evidence --policy policy.json --tenant example --output json
```

Build consumes explicitly selected existing bytes; it does not compile source,
run package scripts, sign a package or manufacture provenance. The optional
SBOM input uses the existing bounded inventory contract. Inspect checks exact
package content and supported semantics. Neither command grants publisher
trust or permission to execute.

Verify shares the node's publisher, independent builder, tenant allowlist,
capsule identity and SBOM checks. The v1 policy requires exactly one publisher
signature and one provenance entry. It samples the local wall clock once and
creates a diagnostic report with exact policy/evidence identities. Its output
explicitly marks target runtime compatibility as `not-evaluated` and durable
policy/clock floors as absent. It opens no admission ledger and cannot create a
catalog grant. A successful local check does not predict admission under a
different node policy or lifecycle state.

Package directories retain their exact `manifest.json`, `config.json` and
declared `layers/` inventory. Detached evidence lives in a separate directory;
its closed [index schema](../schemas/package-evidence-index.schema.json) names
the expected package digest and explicit manifest/configuration/payload files
for signatures, provenance and SBOMs. Empty arrays mean explicit absence.
Selection rejects duplicate JSON keys, unknown fields, null arrays, duplicate
paths, duplicate referrer identities and nonportable paths. Descendants are
opened from one approved capability root without following symlinks; regular
file size and consistency are checked before and after reading.

The CLI limits a package to 32 MiB of layer bytes and each layer to 16 MiB.
Detached evidence has a separate 16 MiB aggregate ceiling, at most eight entries
per kind, a 16 KiB index, 4 KiB referrer manifests and exact `{}` configuration.
Signature payloads are at most 4 KiB, provenance payloads 48 KiB, and SBOM
payloads 1 MiB. The existing evidence codecs impose their additional semantic
and cryptographic limits. These are byte/owner limits, not a process RSS claim.

## OCI transfer

```sh
latent package push package --registry-profile registry.json --reference candidate --evidence-index evidence/index.json --evidence-root evidence
latent package pull --registry-profile registry.json --reference candidate --output-dir received-package --evidence-output received-evidence
```

The closed [registry profile](../schemas/cli-registry-profile.schema.json)
contains an origin, repository, bounded numeric socket addresses, optional
credential-file reference and optional DER CA-file references. Those relative
files are read below the profile's parent using the same regular-file,
no-follow boundary. Credentials are separate from node management tokens and
use the closed [credential file schema](../schemas/cli-registry-credentials.schema.json).
HTTPS is required except for explicitly enabled numeric loopback HTTP fixtures.
The existing OCI adapter enforces origin/repository scope, TLS identity,
credential handling, exact byte hashes, finite transfer ownership and bounded
referrer discovery.

Pull resolves a mutable tag once, then uses its immutable digest. Returned
registry package leases remain held while the client inspects and exports the
bytes. Output directories must be new; no existing output is overwritten.
Evidence exports publish `index.json` last, and an incomplete export is not
reported as a complete package/evidence result.

Push publishes package and referrers as separate registry operations. A partial
transfer preserves known completed digests and an uncertain remaining outcome;
there is no registry transaction across those publications. No command retries
a mutation automatically. The command uses one absolute transfer deadline
(`--rpc-timeout-ms`, default 60 seconds) and observes interruption. Actual
registry cleanup has a separate bounded shutdown interval; canceling a wait
does not prove that a remote upload was undone.

## Managed deployment receipts

Managed Apply/Delete requires a caller-retained operation ID, explicit object
generation and explicit catalog state version. Actor and tenant come from the
authenticated principal. Use `deployment get --operation-snapshot` to read the
object and global state version from one publication, including when the
object is absent. An ordinary Get preserves the existing read path and does
not fabricate a snapshot precondition for unsupported adapters.

The operation ID, action, actor, tenant, normalized request and both
preconditions bind a compact receipt. Routes, desired deployment state and the
receipt are published in one atomic catalog replacement. Exact retained replay
returns that original receipt before checking current state or execution
eligibility; it publishes nothing. Changing any bound request field conflicts.
Delete receipts remain available after the object disappears or is recreated.

The ring is finite. `Unknown` covers never seen and evicted operations; it does
not mean that a request never ran. Requiring the original monotonic state
version prevents an evicted create request from running again after a later
Delete makes the object generation zero. Unrelated catalog writes can therefore
cause an explicit state-version conflict. The client must not silently fetch a
newer precondition or generate a replacement operation ID.

Managed requests are at most 64 KiB of retained typed input and receipts at
most 4 KiB. The default ring retains 256 receipts (hard maximum 1,024) within
one 8 MiB shared metadata allowance for live/next tables, preparation scratch
and retained replies. Read owners are finite. Preparation uses the existing
single control-publication slot; no deployment worker, listener or timer is
added. Legacy writers and every rollout action preserve the operation ring.
The catalog writes format 4 after its first managed deployment operation;
legacy formats 1 through 3 keep their existing absent-field/checksum rules.

## Audit and uncertain results

Managed deployment mutations require configured audit and never fall back to
legacy behavior when that support is unavailable. The server checks the full
response and audit envelope sizes before durable acceptance. After acceptance,
marking mutation started and committing the prepared catalog are synchronous,
with no intervening await. Caller loss after commit can leave an audit outcome
`Unknown`; the retained catalog operation receipt remains independently
inspectable. Startup reconciles exact managed deployment receipts before the
generic release-audit fallback, including when rollout management is disabled.

Keep three separate facts: which catalog publication was selected, whether its
directory synchronization was confirmed, and whether its audit conclusion was
durably acknowledged. A timeout or lost response is not evidence of rollback.
Use the original operation ID for explicit lookup before deciding what to do.
Delete keeps its existing Empty protobuf response and carries bounded operation
and audit metadata; a separate lookup returns the full compact receipt.

## Contracts and SDK scope

The [deployment service](../api/proto/latent/control/v1/deployment.proto),
[release service](../api/proto/latent/control/v1/release.proto),
[rollout service](../api/proto/latent/control/v1/rollout.proto) and
[audit service](../api/proto/latent/control/v1/audit.proto) are authoritative.
Generated Rust RPC clients follow those additive contracts. The six existing
handwritten SDKs expose invocation/guest interfaces; this management extension
does not change their invocation identity or cancellation contracts. Their
interface fixtures remain required CI checks. General SDK transports and
capability/provider convenience models have dedicated Phase 3 tickets
[#227](https://github.com/KirilsTurkins/latent-service-fabric/issues/227),
[#228](https://github.com/KirilsTurkins/latent-service-fabric/issues/228) and
[#230](https://github.com/KirilsTurkins/latent-service-fabric/issues/230).

Validation uses compact file, policy, catalog, RPC and separate client/node
registry workflows. Heavy catalog/benchmark runs remain opt-in.

A rollout candidate manifest must have generation zero and a route weight equal
to the first value in `--weights`. The CLI preserves the supplied manifest. For
example, `--weights 1000,10000` starts with a candidate weight of 1,000 basis
points; a later explicit advance or healthy promotion selects the next stage.

The maintained [workflow runner](../tools/run_phase2_operator_workflow.py) uses
two small compatible capsule revisions and a disposable authenticated TLS
registry. It checks exact rebuild and evidence transfer, current-policy
verification, publication, deployment and rollout recovery, explicit canary
decisions, audit pagination and restart. Client output and node storage occupy
different temporary directories; child processes and registry cleanup have
finite owners and deadlines. CI runs this after the existing Rust tests and
reuses their build outputs.

Its explicit ignored `export_operator_workflow_fixture` policy test creates
fresh publisher and independent builder keys in memory, emits only signed test
evidence and public trust configuration, and requires a new directory selected
by `LSF_OPERATOR_FIXTURE_ROOT`. The signed observation is synthetic test data;
the separate observed-build/OCI integration remains the evidence for actual
source capture and tool execution. No private key, registry content, node
catalog or full process log is retained by the workflow runner.
