# Durable capability policies

Phase 3 delivers a Linux node-owned policy store and evaluator in `latent-policy`,
authenticated `PolicyService` management APIs, and `latent policy` commands.
The closed language is `lsf-capability-policy-v1`; provider selection metadata uses
`lsf-provider-binding-v1`. These are authorization building blocks for the broker
and binding compiler in #204 and #207. Creating a policy does not install a
provider, extend the current guest linker, or make a descriptive DTO executable.
The [host ABI profile](host-abi-profile.md) remains the operation authority.

## Policy language

A policy selects exact trusted tenant, principal kind/subject, executing service,
and tenant-scoped publication, followed by a capability operation and typed
resource. Guest claims, labels and annotations cannot replace those facts.
For example, this document permits a bounded secret read by the stated user in
one publication. The digest below is illustrative and must be replaced by the
actual publication ID; a component digest cannot stand in for it.

```json
{
  "formatVersion": 1,
  "tenant": "acme",
  "rules": [{
    "id": "read-application-key",
    "effect": "allow",
    "principals": [{"kind": "user", "subject": "alice"}],
    "services": ["echo"],
    "publications": ["publication:sha256:1111111111111111111111111111111111111111111111111111111111111111"],
    "capability": "latent:secrets/reader@0.1.0",
    "operations": ["read"],
    "resources": {"kind": "secrets", "references": ["application-key"]},
    "ceiling": {"operations": 1, "inputBytes": 128, "outputBytes": 1024, "wallTimeMillis": 100}
  }]
}
```

No matching allow means deny. A matching deny overrides every allow. Multiple
matching allows intersect their ceilings. Each independently required policy
must allow the operation; policies are never combined into a union of authority.
An unavailable, retired, stale or unsupported authority cannot authorize execution.
Zero operation or wall-time allowance denies admission. Zero input/output bytes
permits only an operation requiring zero of that resource.

All objects are closed. Unknown versions, fields, interfaces, operations, resource
kinds, duplicate JSON keys, repeated set entries and duplicate rule IDs are
rejected. Documents are at most 64 KiB; at most 64 rules and 16 entries per set.
Parser preflight also bounds depth (16), nodes (16,384), string bytes (4096), key
bytes (128), arrays (256) and object fields (32), before typed deserialization.
Identifiers are 1–256 ASCII bytes drawn from letters, digits and `-_.:/@`.
Publications require the exact `publication:sha256:` form. Principal classes are
`user`, `service`, `node`, `trigger` and `administrator`; anonymous never matches.

| Resource kind | Required rule constraints |
| --- | --- |
| `context`, `clock`, `random` | The kind alone; the exact operation still applies. |
| `log` | `levels`: trace, debug, info, warn or error. |
| `http` | Exact `origins` (scheme/host/port), `methods`, and either exact `paths` or `pathPrefixes`. Both path lists must be present. |
| `blob` | Exact `namespaces`. |
| `secrets` | Exact secret `references`, never secret values. |
| `events` | Exact dot-separated `subjects`, with no empty segment or wildcard. |
| `telemetry` | Exact metric `names`. |
| `service` | Exact target `services` and target `publications`. |

HTTP v1 matches normalized `http`/`https` origins with explicit nonzero ports,
canonical IP addresses or lowercase DNS labels. Methods are GET, HEAD, POST, PUT,
PATCH, DELETE and OPTIONS. Paths are absolute ASCII, at most 2048 bytes, with no
control/space, percent encoding, backslash, query, fragment or dot segment.
Prefixes end in `/`, so `/api/` cannot match `/apiculture`. Exact paths and
prefixes are alternatives; origins and methods must also match. This is an
initial normalized path profile, not unrestricted URL parsing. The provider must
derive these facts from the actual destination and separately enforce approved
DNS/redirect/network authority. Caller-supplied target JSON is no such proof.

## Narrowing and provider selection

Imported operations are the outer boundary: an empty import list grants nothing.
Required policy selectors and their resource sets also use empty-as-deny.
An **additional restriction** has a different role: `operations: []` inherits the
already required scope, and omitted `resources` or `ceiling` adds no restriction.
It never creates an allow. Explicit `null` is invalid. The deployment grant,
principal policies, retained provider binding, installed provider configuration
and invocation's remaining allowance all intersect. No stage widens an earlier
stage. Omitted required fields always reject.

Provider binding metadata pins a separately installed profile, configuration
digest and positive epoch. The evaluator requires an exact current match; these
fields do not install a destination or transfer credentials.

```json
{
  "formatVersion": 1,
  "tenant": "acme",
  "capability": "latent:secrets/reader@0.1.0",
  "providerProfile": "local-secrets-v1",
  "configurationDigest": "sha256:2222222222222222222222222222222222222222222222222222222222222222",
  "configurationEpoch": 1,
  "restriction": {"operations": []}
}
```

Ceilings are per-operation constraints, not reservations: operations ≤1,000,000,
input/output ≤64 MiB each, wall time ≤300,000 ms. The broker must reserve actual
invocation/provider budgets before its final guarded start and retain them through
cleanup. Conserved descendant budgets remain #208. A returned ceiling is not a
refund or a substitute for the complete activation resource budget.

## Authority and revocation

Only the configured store creates immutable `PolicySnapshot` values. A snapshot
pins 1–8 distinct required policy revisions and one provider binding in one
tenant, under one counted read owner. `authorize` additionally requires the real
catalog's current scoped publication eligibility. `SealedPolicyDecision` fields
are private; there is no public constructor or cloneable boolean permission.

`PolicyStore::with_current` verifies the exact policy owner, row revisions and
catalog owner at the final guarded-start boundary. Its short synchronous callback
must start only already-reserved work; it must not perform blocking provider I/O.
Updates, revocations, retirement and uncertain persistence invalidate later starts
through held snapshots/decisions, including decisions retained with preparation.
Already-started work retains its own cleanup obligations. Restart verifies history
and issues fresh owner-bound authority; old handles remain retired. Identical Wasm
in another package or tenant does not share publication grants.

Explanation is read-only and authenticated as the current operator. It reports
`allow`, `deny`, or `indeterminate`, with a fixed redacted reason. It omits live
publication eligibility, deployment/import/provider installation and actual budget
reservation, so even an `allow` is not permission or proof an invocation can run.
Unknown operations deny. Old generic action/subject/resource/attribute overrides
are rejected. A typed explanation resource file contains actual descriptive fields:

```json
{"kind": "secrets", "reference": "application-key"}
```

## Durable owner and finite retention

Enable the store explicitly under `capabilityPolicies` in the node configuration:

```json
{
  "formatVersion": 1,
  "maximumControlJobs": 4,
  "store": {
    "maximumRecords": 128,
    "maximumOutcomes": 256,
    "maximumCatalogBytes": 4194304,
    "maximumReadOwners": 32,
    "maximumPageRecords": 16
  }
}
```

Only `formatVersion` is required in this section; omitted store/jobs use the shown
defaults. A supplied store object must specify all five limits. Explicit null is
invalid. Hard maxima are 256 records, 256 outcomes, 16 MiB catalog image, 128 read
owners, 32 rows/page and 16 control jobs; image minimum is 4096 bytes and other
minima are one. Limits are global across tenants and include tombstones/history.
Capacity rejects new work instead of dropping a revision or live reservation.

Storage lives at `dataDirectory/capability-policies`. Linux creates owned 0700
directories and single-link 0600 regular files. It requires private ownership,
no group/other permissions, no symlink traversal and protected ancestors.
Constant filenames are opened relative to the retained root
descriptor and one exclusive owner lock. The canonical image, staged replacement,
small authenticated generation floor and initialization markers occupy at most
two configured image ceilings plus bounded control files. This is a bounded
logical disk allowance, not a filesystem block or whole-process RSS promise.
In memory, the validated live image, compiled rules and bounded staged copy coexist;
read owners and admitted jobs additionally retain bounded requests/responses.

A mutation syncs the staged image, syncs and publishes its exact digest/generation
floor, then publishes the image. Recovery either verifies the current image or
finishes the exact staged image authenticated by the floor. Missing/altered floors,
markers, unsafe file types, corruption and older unauthenticated images fail
closed; no automatic empty-store reset occurs. Interrupted first initialization
may require operator recovery. An uncertain write poisons the live owner until
verified reopen. Privileged deletion/rollback of the whole storage tree is outside
this local protection. Back up and restore the complete stopped store coherently;
do not delete markers, floors or tombstones to bypass capacity or startup errors.

The existing fixed control runtime executes bounded jobs. Reservation precedes
request cloning and includes queue wait and actual blocking work. There is no
per-policy task, listener, network evaluator, scripting language or regex engine.
Contended store/final-start locks reject promptly instead of growing an internal
queue. Cancelled RPC waiters do not refund still-running commits. Four separately
bounded mutation response owners keep held query snapshots from consuming the
entire revocation allowance. Read leases survive protobuf encoding, slow response
bodies and retained frames. Inventory reports control jobs and read owners.
Shutdown retires authority and reports real remaining owners. A kernel filesystem
call that does not return remains an OS limitation; a timeout does not prove it
was stopped or make shutdown clean.

## Operator API and recovery

The existing loopback listener serves authenticated tenant-administrator
`ApplyPolicy`, `GetPolicy`, `ListPolicies`, `DeletePolicy`, `GetPolicyOperation`, and
`EvaluatePolicy`. With no owner, calls return `Unimplemented` after authentication.
Once storage exists, omitting its configuration fails startup. `check-config`
checks that presence/configuration rule without opening or repairing the ledger;
startup performs full history verification.

Each mutation requires an explicit operation ID and expected record generation.
Zero creates only a never-seen tenant/kind/ID; revocation retains a tombstone and
advances the catalog's monotonic generation. Updating even an identical document
creates a fresh revision. A canonical SHA-256 digest identifies document bytes;
array order is retained and significant. It does not identify execution authority.
Within the bounded outcome ring, the same tenant/actor/kind/ID/operation/CAS/document
replays the exact original receipt without reapplying it. Conflicting reuse rejects.
An old successful apply can replay after revocation; `get` still reports revoked.
After outcome eviction, absence means unknown, and stale CAS still cannot recreate
an old record. No receipt proves a durable audit acknowledgement (#210).

Requests are capped at 128 KiB, responses at 1 MiB and configured management limits.
Exact mutation responses are preflighted before persistence. List/get also use
conservative projection allowances, so a smaller page/record limit can reject a
document that the catalog can store. IDs/documents/credentials are absent from
static server errors. Five-minute opaque page tokens authenticate tenant, kind,
generation and offset with a session key. Mutation, expiry and restart invalidate
continuation; the server never silently restarts a page.

Use one bounded command at a time with the existing private CLI profile:

```bash
latent --config client.json policy apply --id application --file policy.json --operation-id policy-create --expected-generation 0
latent --config client.json policy --kind provider-binding apply --id local-secrets --file binding.json --operation-id binding-create --expected-generation 0
latent --config client.json policy get --id application
latent --config client.json policy list --page-size 8
latent --config client.json policy explain --id application --provider-binding local-secrets --service echo --publication-id "$PUBLICATION_ID" --capability latent:secrets/reader@0.1.0 --operation read --resource resource.json
latent --config client.json policy revoke --id application --operation-id policy-revoke --expected-generation 2
latent --config client.json policy operation --operation-id policy-revoke
```

Replace generation `2` with the record actually read. `--kind provider-binding`
selects that record family for apply/get/list/revoke. Explanation accepts up to
seven `--additional-policy` IDs. There is no hidden retry, pagination or invented
operation ID. Apply and revoke failures retain recovery context. After a lost
response, query the same operation ID, compare its identity and revision, and use
`get` to inspect current state. An absent outcome is explicitly unknown. The CLI
validates returned scope, canonical document digest, revision and receipt before
printing success. Public SDK management transports remain #227 and its clients.

The [policy](../../schemas/capability-policy.schema.json),
[binding](../../schemas/capability-provider-binding.schema.json),
[explanation](../../schemas/capability-policy-resource.schema.json), and
[configuration](../../schemas/capability-policy-config.schema.json) schemas describe
the wire inputs; Rust enforces byte bounds, duplicate keys, canonical values and
live authority. The older generic `PolicyManifest` remains descriptive and cannot
be submitted as an executable policy language.

`tools/run_capability_policy_workflow.py --node PATH --cli PATH` exercises a real
Linux node and CLI, historical replay, read-only denial, revocation and restart.
It uses public test credentials, reaps both node processes and removes temporary
storage. It makes zero guest Invokes; provider integration and adversarial calls
are validated by their implementation tickets and #238, not claimed by this test.
