# ADR-0059: Defer general outbound streams; evaluate typed protocol boundaries first

- Date: 2026-09-28
- Status: Proposed for review; decision is **defer production enablement**.
- Investigation: [#696](https://github.com/KirilsTurkins/latent-service-fabric/issues/696)
- Baseline: development `a7b5d2088471b7368cd85ab74f3292afcdfca00e`

## Context

Ordinary third-party dependency support and HTTP adapters do not enable every
non-HTTP library. Adding raw transport also cannot fix JNI, native driver ABIs,
unsupported reflection, Node hosting, arbitrary thread creation or persistent
library state. The six-language [compatibility investigation](../research/outbound-streams/compatibility.md)
identifies real SMTP API seams and a PostgreSQL counterexample without representing
native client execution as capsule compilation evidence.

This is the bounded design investigation requested by #696, not authorization to
ship a socket capability. #679/#680 were open at investigation time; their future
compiler/adapter reports must inform production selection. The current HTTP,
local-service and ownership implementations remain the baseline. ADR-0005,
ADR-0009, ADR-0014, ADR-0025, ADR-0028 and ADR-0032 retain their force.

## Decision

**Defer** a production raw TCP/TLS capability and any new protocol provider in
this change. **Reject** automatic protocol inference, ambient/unrestricted WASI
sockets, invisible reconnect/replay and cross-activation authenticated connection
reuse. **Prefer an explicit typed protocol operation** for the next narrow
application need, using an existing capability to an explicitly operated gateway
or a separately reviewed trusted provider. This preference is an investigation
conclusion, not approval or delivery of a mail/database product.

A merge accepts this research decision and its evidence boundary; it does not
promote the candidate WIT/schema, enable sockets, approve a new host plugin,
certify six libraries, or change any supported HTTP/dependency workflow.

## Alternatives and tradeoffs

| Option | Security and compatibility | Operational/maintenance cost | Result |
| --- | --- | --- | --- |
| Protocol-specific trusted capability/provider | Authorizes operations/resources rather than arbitrary bytes; can protect protocol credentials and report protocol acknowledgements. Does not preserve every stock client API. | Per-protocol Rust parser/client dependency, bounded errors, audit, secrets, operator config and conformance ownership; real host TCB addition requires review. | Useful for a common, well-scoped need; no production implementation approved here. |
| Explicitly operated typed gateway reached via existing HTTP/service capability | Keeps current guest imports and exact HTTP grants. Gateway must independently authenticate tenant/operation and bind downstream authority. A generic proxy or arbitrary SQL endpoint defeats that narrowing. | Another deliberately operated service, deployment/availability/trust boundary, schema versions and observability. Never hide it as a resident per-capsule worker. | Preferred exploration route when an external dependency already exists; POC validates its typed protocol-side operation, not a deployed gateway. |
| Another capsule with typed contract | Can reuse local service invocation, fresh child identity and descendant budgets. | Additional capsule/API ownership, same compiler and capability restrictions. Moving bytes into another capsule cannot conjure missing TCP support. | Useful composition only when its external effect already has an installed authorized provider/gateway. |
| Bounded outbound byte stream | Most useful for compatible custom binary codecs or real transport callbacks; still grants much broader endpoint authority and exposes protocol/session state to guest code. Cannot interpret application rollback or transparently reuse HTTP grants. | New versioned ABI, resource table/lowering, six-language adapters, DNS/TLS hardening, quotas, kernel/allocator measurements, WASI translation and operator qualification. Largest cross-cutting maintenance burden. | Specify exact comparison profile; defer implementation. |

A typed operation can exclude credentials, hostnames, arbitrary commands and
multi-recipient partial submissions from its input. It can say that a peer
accepted a command, but never promises recipient delivery, universal exactly-once
processing or LSF/remote database atomicity. Phase 4 still owns LSF transactions
and durable effects; a database socket or immediate gateway request is not a new
state backend or automatically staged outbox entry.

## Concrete design artifacts

The [candidate profile](../research/outbound-streams/stream-profile.md) specifies
versioned operations/resources, state transitions, concurrency, partial transfer,
unsupported half-close, cleanup, endpoint/port grants, exact TLS scope, credentials,
DNS/SSRF policy, audit, revocation and intersecting byte/handle/deadline budgets.
Its [WIT](../research/outbound-streams/streams.wit) and
[disabled grant schema](../research/outbound-streams/grant.schema.json) remain under
`research/`. Production WIT, ABI recognition, linkers, policy enums, SDKs and
standalone provider installation are unchanged. Standard WASI sockets require a
real semantic adapter; the [comparison](../research/outbound-streams/compatibility.md)
uses the exact `wasi:sockets@0.2.0` surface rather than asserting versionless support.

Reuse would be the existing sealed broker and original ledger, `IoRuntime`,
`IoCall`, `IoTransfer`, shared provider registrations and Store cleanup/quarantine,
not a parallel executor. HTTP #211/#212's destination/trust/ownership and uncertainty
rules inform the design, but an HTTP method/path grant never authorizes raw TCP.
No application-owned connection remains when dormant.

## Executed evidence and negative results

The [local prototype](../research/outbound-streams/README.md) uses Go's real
`net/smtp` against bounded local TCP and TLS SMTP peers. Sixteen top-level Go tests
(plus TLS subcases) cover actual protocol exchange, short reads/writes, before-start
denial with zero connect attempts, TLS trust/hostname failure, partial-write
uncertainty, peer stall, cancellation, forged/foreign/closed handles, provider and
tenant caps, byte/audit exhaustion, revocation, redaction and fresh connections.
The exact command results and measurements live in the source-hashed
[receipt](../research/outbound-streams/evidence/receipt.json). Five Python checks
validate research schema examples/rejections and acceptance-map integrity.

The peer records DATA acceptance before losing its final reply; the client reports
uncertainty and does not replay. Cancellation retains one handle, one active owner
and 114,971 logical bytes at a controlled retirement boundary and releases them
only after cleanup returns. These are functional/model ownership observations,
not throughput, exact RSS, remote rollback or OS scheduling guarantees.

The [initial failed address test](../research/outbound-streams/evidence/development-negative.json)
is retained with the superseded source and digest. A draft partial blacklist
missed an IPv6 documentation address. The final POC permits **only explicitly
configured loopback**, while production design requires reuse of the full existing
address policy. This negative result argues against a casually duplicated network
policy implementation.

The Go test boundary is deliberately native. It models production ownership but
**does not execute the Rust broker or real guest components**. Rust/Cargo, a local
production checkout, WIT parser and guest compiler inputs were unavailable in the
local environment. No package build claim is inferred from an upstream API table.
The Go TLS/textproto allocation allowances and zeroization scope are also not a
hostile-peer memory/security proof. These are explicit reasons to defer production,
not missing results relabelled as passes. The [requirement map](../research/outbound-streams/requirements.json)
distinguishes actual tests, design artifacts and unexecuted qualification.

## Consequences and approval gate

Existing ordinary library ingestion and HTTP transport work remains independent
of this investigation. Developers can supply unprivileged adapter code under the
same captured-dependency rules; no selected-package catalogue or maintainer library
approval gate is introduced. APIs whose compiler/runtime semantics cannot be
represented fail honestly rather than receiving fake successful socket handles.

No production direction is approved by this PR, so **no implementation,
conformance or operator tickets are created merely to presume such approval**.
If maintainers later approve a specific protocol boundary or raw profile, create
three separately scoped issues: production authority/ownership integration,
real-component/library and adversarial conformance, and protected operator
configuration/audit/credential lifecycle. Each must identify its approved ADR
revision, exact source/WIT/compiler profile, explicit capability grants, budgets,
recovery semantics and finite acceptance evidence. A new decision or revision
must state which deferred gate it satisfies; changing this ADR's status alone
cannot make a capability available.
