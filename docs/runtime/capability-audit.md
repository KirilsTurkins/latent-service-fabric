# Capability audit and inspection

Phase 3 [#210](https://github.com/KirilsTurkins/latent-service-fabric/issues/210)
connects the [sealed broker](capability-broker.md) to the existing
[durable audit owner](../phase-2-audit.md). It adds typed capability evidence,
required audit admission and scoped `CapabilityService` inspection. Remaining
HTTP, blob, secret and event providers have their own implementation tickets.

## Required recording and optional observations

An allow rule can specify `"requireAudit": true`. Matching allows and independent
policies intersect their ceilings and combine this requirement with logical OR;
any matching deny still wins. Omission preserves earlier canonical policy bytes
and means false. Present null and nonboolean values are rejected.

A configured embedding calls
`ActivationCapabilityBroker::with_audit(handle, observations)` before registering
providers or compiling plans. Standalone composition requires the same audit
owner as management. Normal standalone provider configuration remains its own
Phase 3 ticket.

`prepare_owned_dispatch` retains the exact handle and provisional budget owners.
`CapabilityDispatch::dispatch` preflights applicable terminal records, reserves
both records and awaits a durable attempt. It then rechecks policy, publication,
provider, route, cancellation and the original monotonic deadline before budget
commitment and dispatch. No audit wait holds an authority fence or Wasmtime Store
borrow. A full, unavailable or undersized sink denies the new operation and
releases provisional cumulative reservations.

`dispatch_audited` and `call` offer the same barrier for existing handles. The
synchronous dispatch API rejects required-audit calls. Frozen synchronous guest
imports therefore fail closed when policy requires that asynchronous barrier;
their WIT signatures are unchanged. The canonical async
[local-service adapter](local-service-invocation.md) uses the barrier directly.

The journal retains its single outstanding critical-operation limit. Concurrent
required calls, including a required child call while its parent owns that slot,
can receive capacity rejection. There is no unbounded audit queue, implicit retry
or mandatory journal event for every Invoke. Optional observations may be dropped
under saturation without preventing a nonrequired provider call.

## Captured identity and evidence

The broker captures trusted tenant/principal and activation/parent/root lineage;
exact publication, component, deployment, revision, route and lifecycle
generations; binding-definition digest; provider-binding and policy revisions;
and provider profile, configuration digest and epoch. Required calls fail if this
sealed-session provenance is incomplete.

Grant observations fingerprint resource selection. Call records fingerprint the
actual provider request. Typed providers use `CapabilityRequestDigest::from_parts`
over bounded input fields absent from the byte input. Missing fingerprints deny
required typed calls and suppress optional incomplete observations. Local service
calls include target, payload, media type, metadata and call options. Records and
metric names never contain raw payloads, credentials, resource selectors or secret
references. Digests are correlation fingerprints, not encryption or secrecy
guarantees for guessable inputs.

`CapabilityCall` attempts and outcomes retain matching identities. Closed decoding,
terminal preflight and recovery reject contradictory associations and provider
outcome classes. Optional kinds are `CapabilityGrantAllowed`,
`CapabilityGrantDenied` and `CapabilityProviderOutcome`.

| Evidence | Provider boundary |
| --- | --- |
| `LocalDispatchAccepted` | The node accepted the child lifecycle; its guest may subsequently fail. |
| `HttpResponseReceived` | The HTTP provider received a response, without application transaction guarantees. |
| `BrokerAcknowledged` | The event broker acknowledged publication, not consumer processing. |
| `BlobSealed` | The blob provider completed sealing. |
| `SecretResolved` | The provider resolved a secret; the value is never recorded. |
| `HostCompleted` | A built-in host operation completed, such as sampling a clock or accepting a bounded log entry. |
| `NotStarted`, `Rejected`, `Unknown` | No dispatch, a known rejection, or insufficient provider-result evidence. |

Providers call `record_provider_outcome` only after observing that boundary.
Cancellation and unclassified terminal paths stay unknown. Retained context
lowering can finish without proof of guest delivery. An idempotency key, Allow DTO
or audit sequence never establishes exactly-once execution, rollback or consumer
processing.

`OwnedCapabilityResponse` exposes `provider_outcome` separately from
`audit_durability`. `finish_audit` returns a durable sequence when acknowledged.
A failed terminal write preserves the provider result with `OutcomeUnknown`
recording status. Closing the journal waits for accepted owners; dropping a
waiter does not cancel its prepaid terminal append. Restart reconciliation marks
interrupted capability attempts unknown and never invokes the provider again.

## Bounded management inspection

`CapabilityService.ListCapabilities` requires an explicit `deployment_id` and a
tenant administrator. It returns compiled operations, definition/binding/policy/
provider revisions, sampled state and tenant usage. Contract-prefix and provider
filters are bounded. Pages contain at most 128 bindings; cursors pin route
generation, catalog transaction, tenant, authenticated subject and filters.
Changing either catalog version invalidates a cursor.

States distinguish current configuration, changed/revoked policy, unavailable
provider/publication/route and indeterminate reads. A deployment without a compiled
plan reports `binding-plan-unavailable`, without inventing its cause. Foreign and
nonexistent deployments are rejected without revealing their metadata.

`ExplainCapabilityGrant` evaluates a bounded typed `resource_document` against
compiled restrictions. An optional `hypothetical_subject` selects a principal
kind/subject/service within the authenticated tenant. Legacy principal and
attribute fields are rejected; no claims or alternate tenant are accepted.
The response never echoes resource selectors. Allow is descriptive and subject
to live admission: it reserves no activation budget and returns no sealed grant.

Both RPCs use the existing bounded policy control runtime and read-owner quota.
A response lease lasts through protobuf encoding, transport body and frame
ownership. Oversized responses, expired deadlines and full owners fail without
extra queues. Audit queries retain their independent authorization, frozen cursor
horizon, loss accounting and response leases.

Tenant counters cover live session owners, retired sessions with retained work,
handles, calls, waiting owners, results and reserved input/output bytes. They sum
immediate child reservations and delegated memory for session-held ledgers, with
an explicit count of ledgers without delegation. Ancestor reservations can overlap:
delegated memory is a logical sum, not uniquely allocated bytes or RSS. Cancellation
does not refund actual retained work. Counters are sampled rather than atomic.

`include_node_usage` additionally requires the trusted node-operator claim. Fixed
`broker_*`, `pool_*`, `io_*` and `audit_*` counters come from actual shared owners,
including retained connections, failed cleanup and outstanding I/O.
`audit_capture_dropped` counts pre-sink capture failures; `audit_dropped_observations`
counts sink rejection. Missing owners are explicitly unavailable. No credential,
foreign identity or resource-specific metric label is exported.

The weak diagnostic registry owns no provider task, guest Store or execution
permission. Compact accounting can remain until the final resource or observer is
released. Pools register a weak observation reference once; inspection cannot
replace their owner or expand capacity.
