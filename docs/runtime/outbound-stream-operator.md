# Protected outbound stream administration

The stream installation remains explicitly gated by the development build
features and the architecture/security prerequisite in
[#737](https://github.com/KirilsTurkins/latent-service-fabric/issues/737).
The ordinary default node refuses this installation. The helper enables no
production profile and installs no socket or daemon. Preparation runs only the
selected node's bounded configuration check.

`tools.outbound_stream_operator.configure()` prepares a closed node input for
an explicitly selected development profile. It preserves existing credentials,
budgets, providers and bindings, validates the maintained provider schemas and
the original 64 KiB node input bound, and refuses an input overwrite of an
already configured stream provider. Save this input in an owned protected file
and run the actual node's `check-config` before startup; schema validation is
not a substitute for the node's platform, permission or feature checks.

The `latent-dev stream-operator prepare` command performs that protected preparation and invokes
one actual `latentd check-config` using the selected node binary. Put the
installation and its consumer bindings in a private `installation.json`:

```json
{
  "installation": {
    "identity": {"id": "streams", "tenant": "examples", "service": "stream-host", "epoch": 1},
    "configuration": {
      "formatVersion": 1,
      "profile": "lsf-outbound-streams-v1",
      "destinations": [{
        "endpoint": {"host": "127.0.0.1", "port": 32123, "transport": "tcp"},
        "addresses": {"networks": ["127.0.0.1/32"], "specialAddresses": ["127.0.0.1"]},
        "resolution": {"kind": "static", "addresses": ["127.0.0.1"]}
      }],
      "limits": {"maximumTransferBytes": 65536, "idleTimeoutMillis": 1000, "absoluteTimeoutMillis": 5000}
    }
  },
  "bindings": [{"name": "mail-stream", "tenant": "examples", "consumerService": "examples/mail", "providerService": "stream-host", "contract": "latent:network/streams@0.1.0", "providerBinding": "stream-installed"}]
}
```

Use an existing protected base node configuration with the Phase 3 budget,
durable audit and capability-policy owners described in the
[standalone reference](../reference/standalone-streams.md). Its credentials and
all existing HTTP providers and bindings are preserved. The output's parent
must already be private, and the output must not exist:

```sh
latent-dev stream-operator prepare \
  --node /path/to/latentd --base-config /private/node/base.json \
  --installation-record /private/node/installation.json \
  --output /private/node/prepared.json --development-profile
```

The frozen developer frontend includes this operator, both canonical provider
schemas and its locked schema-validator dependencies, using the existing
frontend file, license and provenance inventory. Contributors can invoke the
same owner with `python3.13 -m tools.outbound_stream_operator`.

The output is a new protected file. Preparation never overwrites a running
configuration or starts a node. The selected node performs its own platform,
protected-input and feature checks, with no profile fallback. A refused or
interrupted check returns failure and retains the file for private owner
review; retrying requires a separately named new output. The command invokes
no provider mutation or grant RPC. It bounds the check to 30 seconds and 64 KiB
per output stream through the existing process owner, rechecks the prepared
bytes afterwards, and emits no node output or input paths. It binds the selected
node executable (at most 256 MiB) by its actual SHA-256 and byte size before and
after that one check; a changed executable fails explicitly. This executable
identity does not attest its source, version, publisher or installation. An accepted check
reports `providerReadiness: "not-observed"` and `executionPermission: false`:
it establishes neither actual installation nor a working stream. Current
kernel/provider qualification gates still prevent production enablement. The
frontend packaging campaign exercises the actual frozen command outside the
checkout with private files and an explicit Python configuration-check process
double, including refused-check retention. That packaging observation is not
real `latentd` installation or controlled-peer stream qualification; its receipt
keeps `realLatentd: false` and `providerReadiness: "not-observed"`.

For an already installed provider, put this specification in a private
directory. Use the actual provider descriptor from the node startup record and
the exact signed publication selected for the consumer:

```json
{
  "node": "operator-workflow-test",
  "tenant": "examples",
  "provider": {
    "id": "streams",
    "tenant": "examples",
    "service": "stream-host",
    "capability": "latent:network/streams@0.1.0",
    "profile": "lsf-outbound-streams-v1",
    "configurationDigest": "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "configurationEpoch": "1"
  },
  "consumer": "examples/mail",
  "publication": "publication-v1:sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
  "principal": {"kind": "administrator", "subject": "workflow-operator"},
  "destination": {"host": "127.0.0.1", "port": 32123, "transport": "tcp"},
  "bindingId": "stream-installed",
  "policyId": "stream-allow"
}
```

The digests above are placeholders. The descriptor is installation information,
not authority. The existing policy RPC authenticates the supplied private
client configuration and requires administrator authority in the selected
tenant. Global usage inspection additionally requires the node operator claim.
Keep the specification, client configuration and state directories private;
files and ancestors must satisfy the maintained ownership/link protections.

```sh
mkdir -m 700 stream-operator-state
python3.13 -m tools.outbound_stream_operator grant \
  --cli /path/to/latent --client-config /private/client/config.json \
  --state-dir "$PWD/stream-operator-state" \
  --specification /private/operator/stream.json
```

The returned capability/policy pair belongs in the normal deployment's explicit
grants. The helper applies one exact provider binding followed by an audited
policy limited to the selected principal, consumer, publication and TCP
destination. It uses all eight stream operations with finite original profile
ceilings. It grants no HTTP authority, arbitrary destination or host TLS profile.
The node still checks the binding, publication and provider currentness during
actual admission and operations.

Use the same arguments with `revoke` to publish a durable deny at the last
confirmed owned policy generation. The helper neither deletes another owner's
record nor refunds physical resources; inspect actual node usage and retirement
after revocation. Use `inspect --deployment NAME` for the bounded existing
capability inspection RPC. It selects the exact stream contract and provider
profile, and refuses a deployment whose returned publication differs from the
protected owner, including a missing publication. Binding generations and
changed/revoked/unavailable states remain descriptive diagnostics, even when
they differ from the saved provider descriptor. Empty results and unavailable
counters remain unavailable; inspection grants no execution permission or
readiness and changes no local owner or remote grant.

Each mutation records its original intent and operation identity in protected
state before dispatch. An uncertain response or transport exception retains
that intent and prevents subsequent mutations. `recover` reads the original
public operation receipt and current policy, validates the exact original
document, and settles local state. It never resubmits an apply. An unknown or
expired receipt remains unresolved. Confirmed repeated requests read the owned
record without applying it again; foreign or changed records require explicit
operator review. Changing the publication, endpoint, provider identity or private
client configuration fails closed under the existing owner. A new provider
generation must be adopted explicitly as described below.

The owning Linux x86-64 node built with `development-outbound-streams` supports
protected reload. Keep the same owned configuration path and change only the
stream limits and a strictly newer `identity.epoch`. Every other field remains
bound to startup, including destinations, DNS/address constraints, tenant,
credentials, consumer bindings and provider identity. Replacement files must
still satisfy the original protected ownership, single-link, mode, input-size
and closed-type checks. `SIGHUP` reopens and validates that file before rotating
the actual provider. Before reading, the owner reserves six finite 1 MiB scratch
charges for the bounded raw/typed/JSON/canonical/derived configuration stages
under the existing 8 MiB provider pool. Insufficient shared capacity rejects the
reload before parsing or rotation and drops any partial scratch reservations;
it never widens that pool or refunds another live owner's charge. All changes
force retirement: accepted sessions are never
migrated, and their physical charges remain until cleanup. Repeating the same
epoch is rejected without another rotation.

Use `latent-dev stream-operator prepare-rotation` to construct a new private
candidate for that existing reload rule. Keep the rotation record private and
set `formatVersion` to `1`, `provider` to the exact `{id, tenant, service}` from
the base file, `expectedEpoch` to that file's epoch, `newEpoch` to a strictly
newer positive `u64`, and `limits` to all three original bounded limit fields.
The [closed record schema](../../schemas/outbound-stream-rotation.schema.json)
reuses the canonical provider identity and limits. For example:

```json
{
  "formatVersion": 1,
  "provider": {"id": "streams", "tenant": "examples", "service": "stream-host"},
  "expectedEpoch": 1,
  "newEpoch": 2,
  "limits": {"maximumTransferBytes": 32768, "idleTimeoutMillis": 500, "absoluteTimeoutMillis": 4000}
}
```

```sh
latent-dev stream-operator prepare-rotation \
  --node /path/to/latentd --base-config /private/node/config.json \
  --rotation-record /private/operator/rotation.json \
  --output /private/operator/rotation-candidate.json --development-profile
```

Only epoch and limits change in the candidate; all other configuration fields,
credentials, destinations, DNS/address constraints and bindings stay exact.
The command uses the same protected-input, create-only output, selected-binary
identity, bounded `check-config` and redacted failure rules as initial preparation.
A refused or uncertain check retains the private candidate. It never replaces
the live file, sends a signal, rotates sessions or changes grants.
`expectedEpoch` checks only the supplied file; it does not observe the live
provider generation. Separately confirm the actual node owner's currentness
before applying a reviewed candidate through its existing protected reload path.
The development flag grants no installation or production override. The ordinary
node's compiled-profile refusal remains a refusal, not readiness.

The bounded `stream-control` status line distinguishes `configuredGeneration`
from `installedBindingGeneration`. The first identifies the actual stream
manager; the second identifies the last confirmed catalog publication. If
rotation succeeds but publication fails, `bindingPublicationPending` stays
true. The old reference remains fenced; no retry or rollback follows silently.
`failureCode` contains only the platform code, and the line contains no
credentials or protocol bytes. After reviewing the failure, an explicit
`SIGUSR1` publishes the current reference without rotating it again. The
publication can still produce unavailable plans until exact grants are present;
every status and inspection response reports `executionPermission: false`.

Save the actual new `provider` descriptor from that status in another protected
file. Use `adopt --provider-record /private/operator/new-provider.json` with the
existing specification and state directory. Adoption requires a strictly newer
epoch, the same provider identity/profile/tenant, no unresolved operation, and
unchanged owned policy receipts. It only records the descriptor; it sends no
mutation and grants no execution authority. Update only `provider` in the
specification to match, then explicitly run `grant` to apply and confirm the new
provider-binding record. Send `SIGUSR1` once more to compile that exact binding
into the catalog. The original publication, principal, endpoint, client secret
owner and all finite ceilings remain fixed. No receipt recovery resubmits a
mutation or repeats a side effect.

`SIGUSR2` explicitly retires/drains streams under the existing 30-second
deadline. A retained owner remains charged and visible; a timeout is not a
refund. Drain permanently stops this stream manager, so fresh work requires a
normal node restart. `SIGINT` and `SIGTERM` retain their original shutdown path
and interrupt a pending control operation. Restart uses the protected file's
current generation and actual startup provider descriptors; previous status
lines are historical evidence, not confirmation of the new process's catalog.
Ordinary default builds allocate no reload owner and register no stream signals.

The [source-bound packaging observation](../testing/evidence/stream-operator-packaging-2026-10-23.json)
records the actual Linux and Windows frozen frontend checks on source
`380c7df8f26ec3f0f6e54d616e8d08b80cb5cc73`: Linux passed all 38 source controls;
Windows passed 37 and retained one existing POSIX-only skip. Both actual
packaged preparation/refusal smoke cases passed outside the checkout, with the
explicit Python process double and no real `latentd` or provider readiness claim.
The first Linux native-library inventory failure remains recorded; the corrected
inventory accepts only original pinned-wheel RECORD hash/size members, preserving
unknown-owner refusal. Both complete artifacts, file inventories and 105 helper
source/schema materials per platform were independently authenticated. These
observations do not enable production or complete any whole #739 criterion.

The later [actual-node configuration observation](../testing/evidence/stream-operator-actual-node-2026-10-23.json)
reuses that exact Linux frontend with the separately authenticated node built on
`277c8104499d414053573bce066b5e9091e74a20`. All eight configuration cases passed:
the complete protected baseline was accepted, the explicit stream addition was
refused with the private candidate retained, and existing-output and unsafe-input
checks failed closed. The public node diagnostic is only
`configuration: invalid-argument`; attribution to the compiled feature gate depends on the
frozen source and successful baseline. The first acquisition deadline failure
remains recorded. Four bounded reads of the same sealed frontend archive reduced
the complete program to 100.3 seconds without raising its 240-second budget.
This observation starts no node or provider, invokes no socket, and establishes
neither installation nor readiness.

Host TLS credential rotation, actual signed standard-library workflows, and the
complete operator acceptance matrix remain separate required observations for
[#739](https://github.com/KirilsTurkins/latent-service-fabric/issues/739).
