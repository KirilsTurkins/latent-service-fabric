# Server source declarations and shared ingress

`tools/server_source.py` implements the closed `lsf.server.source.v1` declaration
and `lsf.server.source.profile.v1` compiler profile. `tools/server_routes.py` and
`tools/server_capsule.py` turn a selected declaration into finite existing
`HttpTrigger` operations. These are implemented common contracts and tooling.
They do not establish that a language compiler translates its ordinary server
API, or that its final component has passed listener qualification.

The target is the existing
[`latent:web/application@0.1.0` contract](../protocol/http-applications.md),
with a single `handle` export and `buffered-v1` values. The compiler's `inspect`
step compares the final emitted interface, including its complete function/type
signature, with the staged authoritative WIT. An import-name scan alone cannot
qualify an export. The profile captures exact source APIs, compiler, runtime and
automatic adapter digests, initialization behavior, bounds and unsupported
members. A changed profile gets a changed digest; qualification for previous
bytes cannot transfer to it.

## Language applicability

| Source path | Ordinary/default source delivery | Runtime-dependent server behavior | Developer extension |
| --- | --- | --- | --- |
| Java `HttpServer` | Consumer implementation and real ingress qualification tracked in #728 | Executor/task/timer server lifecycle consumes #736/#741 | Separately labelled, never ordinary-source proof |
| Rust server APIs | No common server-source compiler adapter delivered | Selected runtime port #743 needs separate server lifecycle integration | Finite declarations can be used by an explicit extension |
| C server APIs | No common server-source compiler adapter delivered | Selected runtime port #744 needs separate server lifecycle integration | Finite declarations can be used by an explicit extension |
| TypeScript server APIs | No common server-source compiler adapter delivered | Selected runtime port #745 needs separate server lifecycle integration | Finite declarations can be used by an explicit extension |
| Go server APIs | No common server-source compiler adapter delivered | Selected runtime port #742 needs separate server lifecycle integration | Finite declarations can be used by an explicit extension |
| .NET server APIs | No common server-source compiler adapter delivered | Selected runtime port #746 needs separate server lifecycle integration | Finite declarations can be used by an explicit extension |

This matrix describes current implementation boundaries. The shared declaration
format does not certify six language adapters or general socket listeners.

## Captured declarations

The language compiler supplies a bounded AST extraction plan, never the result
of executing application startup on the build host. The plan identifies the
original initializer, logical endpoints, address/port/backlog inputs, context
matching, handler symbols and captured source locations. An explicit developer
extension has a different extraction/adapter kind and cannot claim an automatic
compiler path. Source locations must belong to actual captured UTF-8 files.

There are at most 16 logical endpoints and 64 contexts. Context paths use a
1024-byte ASCII canonical-path subset: no encoded aliases, query, fragment,
dot segments, empty segments, wildcard or reserved `/_lsf` path. Context case
and trailing slash remain meaningful. This finite profile does not expose an
arbitrary raw request target or infer a binary protocol.

The emitted `server-source.json` binds source inventory, component, profile,
compiler, adapter, runtime, extracted configuration and final WIT surface.
`package` validates the component association and adds it as a package asset
before signing. A declaration's `authority` is always `none`. Its logical bind
address is `wildcard` or `loopback`; its positive port is not permission to bind
that port, expose a hostname or open any guest socket. Ephemeral-port discovery
has no mapping in this common profile.

Fresh-original-entrypoint initialization is part of the selected profile. The
language adapter must run all permitted initialization and code after `start`
inside each actual activation, reconstruct handlers/statics/captures freshly,
and implement illegal lifecycle transitions. This tool never deletes startup
instructions, manufactures a successful stub, or discards accepted work. Any
advertised tasks, waits or timers must use the selected activation runtime and
drain before response eligibility. No listener, accept loop, application heap,
worker or continuation may survive retirement. Translation and these execution
requirements remain language qualification criteria.

## Explicit mounts and matching

An operator supplies `lsf.server.mounts.v1` separately from source declarations:

```json
{
  "schemaVersion": "lsf.server.mounts.v1",
  "profileDigest": "sha256:<exact-selected-profile>",
  "mounts": [{
    "endpoint": "server",
    "name": "application",
    "scheme": "http",
    "host": "app.example.invalid",
    "path": "/api",
    "pathMatch": "prefix",
    "methods": ["GET", "HEAD"],
    "dispatch": "guest"
  }]
}
```

The digest above is explanatory, not a deployable placeholder. DNS and IPv4
authorities must already be canonical lowercase values; explicit default ports,
leading-zero ports/IPv4 addresses, userinfo, wildcard DNS, invalid labels and
trailing DNS dots are rejected. IPv6 mounts require a subsequent profile.

An exact source context can map to an exact host trigger. A segment-prefix
context can map to an equivalent host prefix. `direct` dispatch must have one
context and an equivalent path/matching pair. Other matching requires explicitly
selected `guest` dispatch and an encompassing authorized finite mount.

Java literal `/api/hey` accepts `/api/heyday`. Host prefix `/api/hey` cannot
represent that behavior and is rejected even when it looks narrower. An
explicit `/api` prefix can encompass it; the invocation-local Java dispatcher
then performs case-sensitive longest literal matching. `/hey` requires an
explicit `/` mount in this host grammar. The tool never infers that broader
ownership. The host remains responsible for canonicalization, reserved routes,
tenant authorization, conflicts and public ingress policy. Query data never
participates in path selection and there is no second decoding pass.

Methods are explicit; selecting GET does not add HEAD. There are at most 32
resulting triggers. Bounded guest dispatch must return missing-context/404 and
preserve every claimed method/URI/body/header/lifecycle behavior. The request
body is at most 64 KiB and response body at most 256 KiB; repeated headers and
cookies retain ordering. Host principal/trace/deadline come from host context.
Buffered sealing or local flush is not client receipt, physical delivery or
rollback of an outbound effect. Outbound calls keep their existing grants,
original ledger/deadline and uncertainty; HTTP grants never become stream grants.

## Published route selection and recovery

Build and sign/admit/deploy the actual component with the existing toolkit.
Then use the maintained `latent` binary and explicit protected client profile:

```text
python tools/server_capsule.py --binary /sdk/bin/latent --config client.json --state /private/server-route-state --tenant examples --route server plan --declaration build/server-source.json --component build/component.wasm --source-inputs build/source-inputs.json --profile build/server-profile.json --mounts mounts.json
```

Use the same arguments with `apply` to perform the planned trigger writes.
The state directory must be private; a missing direct child is created privately.
`plan` is read-only with respect to the remote catalog. It reads the actual
authenticated deployment and route snapshot, verifies tenant/service/component,
requires one exact full-weight revision, and selects its actual publication,
positive deployment generation and revision. It does not invent IDs, execute
application initialization or promote a canary by inference. This is route
selection tooling; declaration/package validation and signed node admission
are separate required trust steps.

Each write observes current ownership and uses the existing object-generation
and catalog-state CAS fields. The protected local journal persists the exact
operation before dispatch. Invalid declarations are rejected before catalog
reads/writes. An unowned route or concurrent change cannot be overwritten.
Rejected writes retain last-good records. The CLI/server supplies authenticated
authorization, audit acknowledgements, conflicts and exact publication pins;
the local configuration grants no management permission to a guest.

`recover` queries only the original operation ID and confirms its tenant,
target, preconditions, generation and current exact manifest before settling.
Unknown/expired receipts or changed objects retain the pending intent and do
not cause a replay. `rollback NAME ...` is a new CAS mutation to retained
previous manifests; the server still rejects removed/revoked old revisions.
`remove NAME ...` deletes only owned objects, using original operation lookup
for its full receipt. Removed mounts must be explicitly selected before a plan
can replace the set. There is no atomic multi-route publication promise: a
later failure can leave earlier individually confirmed writes in place.

`inspect` distinguishes declared input from currently published manifests and
reports `reachability: not-observed` and `executionPermission: false`. Actual
reachability, denied routes without handler invocation, in-flight revision
pinning, deadline/disconnect cleanup and dormant-state measurements need the
real shared-listener qualification, not this inspection or the catalog model.

The common conformance tests exercise closed declarations, captured attribution,
route equivalence, explicit methods, profile/component/source tampering, catalog
CAS, lost replies, unknown original receipts, retained last-good records and
owned rollback/removal. They are compiler/tooling and native model evidence.
Issue #727's real component integration and #728's source-API translation remain
separate acceptance work; handwritten web exports do not count as Java lowering.
