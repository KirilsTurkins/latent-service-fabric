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
operator review. Changing the specification, provider generation, publication,
endpoint or private client configuration fails closed under the existing owner.

Live provider configuration rotation and drain require the coupled node owner:
retire the old stream generation while retaining its physical charges, install
the new immutable reference, and publish newly compiled binding references.
The public policy helper does not invoke a standalone lifecycle rotation or
claim the old catalog has adopted a new provider. Host TLS credential rotation,
actual signed standard-library workflows, and the complete operator acceptance
matrix remain separate required observations for
[#739](https://github.com/KirilsTurkins/latent-service-fabric/issues/739).
