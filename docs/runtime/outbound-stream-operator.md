# Protected outbound stream administration

The stream installation remains explicitly gated by the development build
features and the architecture/security prerequisite in
[#737](https://github.com/KirilsTurkins/latent-service-fabric/issues/737).
The ordinary default node refuses this installation. The helper enables no
production profile and installs no socket or process.

`tools.outbound_stream_operator.configure()` prepares a closed node input for
an explicitly selected development profile. It preserves existing credentials,
budgets, providers and bindings, validates the maintained provider schemas and
the original 64 KiB node input bound, and refuses an input overwrite of an
already configured stream provider. Save this input in an owned protected file
and run the actual node's `check-config` before startup; schema validation is
not a substitute for the node's platform, permission or feature checks.

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
capability inspection RPC. Unavailable counters remain unavailable, and the
inspection response grants no execution permission.

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

Host TLS credential rotation, actual signed standard-library workflows, and the
complete operator acceptance matrix remain separate required observations for
[#739](https://github.com/KirilsTurkins/latent-service-fabric/issues/739).
