# Direct transaction HTTP binding v1

PR #828 connects this profile to the installed transaction owners introduced by
PR #823. It serves direct commands, fresh queries and explicit original-result
reads through the existing shared HTTP listener. Namespace creation remains an
explicit authorized management operation; restart captures its actual incarnation.

The `transaction-http-v1` application profile uses the shared HTTP ingress and
the normal activation owner. Its fixed target is the selected deployment,
publication, contract and function. It does not create a cross-service
transaction through a stateless adapter's synchronous child call.

Results use host-owned JSON framing, a 128 KiB application-result limit and
`Cache-Control: no-store`. Commands validate that representation before durable
completion. Every socket write and flush poll checks the retained current data
permission. A cleanup failure remains a delivery diagnostic alongside the durable
receipt. HTTP status does not turn uncertainty into an abort.

Real signed Java, browser and complete recovery qualification remain acceptance
work for #409/#718. Portable mapping, signed fixture execution and provider tests
retain separate evidence boundaries.

## Installed scope

A route contains the six existing strings `profile`, `scheme`, `host`, `path`,
`pathMatch` and `method`, plus these required strings:

| Field | Meaning |
| --- | --- |
| `transactionMode` | Exactly `command`, `query` or `result` |
| `namespace` | Fixed namespace identity, at most 256 UTF-8 bytes |
| `incarnation` | Canonical nonzero unsigned decimal incarnation |
| `stateSchema` | Exact canonical SHA-256 schema digest |
| `companionDigest` | SHA-256 of the signed transaction companion bytes |
| `stateBinding` | Fixed installed namespace policy binding |
| `resultPolicy` | Fixed installed result-read policy identity |

Optional `entity` fixes an entity identity. Optional `preconditionKey` is a
canonical padded base64 business key of at most 1024 bytes and is permitted only
for command routes. Unknown fields, nested configuration, missing links and
unsupported method/mode pairs are rejected. Route descriptions and version
tokens are descriptive values, never grants. The state runtime must verify the
companion's signed package association, operation and publication links before
issuing an execution owner, then recheck current caller/policy authority.

## Original request facts

Commands use POST, PUT, PATCH or DELETE and exactly one `Idempotency-Key` of at
most 256 UTF-8 bytes. Whitespace, control bytes and duplicate fields are rejected.
The body is the ordinary `application/vnd.latent.wit-values.v1+json` parameter
frame, within the unchanged 64 KiB transport body ceiling. Command query strings
are unsupported. The canonical method/path, typed parameters and original
preconditions are business input; credentials, cookies, CSRF material, traces and
transport deadlines are excluded.

`If-Match: "absent"` preserves an absent-value precondition. A present precondition
is a quoted canonical padded-base64 67-byte `SV` format-2 token for the fixed
business key. Wildcards, weak tags, lists and short generation counters are
rejected. A conflict never replaces the original token with a fresh one.

Queries use GET or HEAD. An optional `input` query parameter carries the ordinary
typed parameter frame in canonical base64url without padding, after the shared
target parser's single URL normalization. It is the only supported query field;
the default parameter frame is `[]`. A valid command key is ignored and creates
no command identity. A query cannot carry a body, write precondition or command
method. Optional `If-State-View` retains the entire canonical-base64 67-byte `NV`
format-2 token for a minimum observed view. The host's returned query view token
describes that exact native snapshot and does not assert commitment.

Result requests use GET with the original `Idempotency-Key` and no business
parameters, body, write precondition or minimum-view token. The runtime performs
an explicit finite authorized lookup; it does not run the original mutating guest
or mint application/management authority from knowledge of a command ID.

A retry after a proven abort is explicit. The original `Idempotency-Key` remains
unchanged, and the request supplies both `Command-Retry-Key` (a separate bounded
retry request identity) and `Command-Abort-Fence`. The latter is canonical padded
base64 of a closed JSON object with `command-id`, `attempt-id`, `transaction-id`
and `owner-fence`, copied from the actual server-issued aborted receipt. The
command and transaction identities are lowercase 64-character hex. The attempt
is a canonical decimal counter from 1 through 16; `owner-fence` is canonical base64 of
the actual 32-byte abort proof. The coordinator must match the original stored
attempt, original fingerprint and current authority before accepting a retry.
Malformed, incomplete or unsupported pairs fail before claim; queries and result
lookups reject retry fields. A timeout, unknown result or disconnected socket
never manufactures an abort proof or triggers a retry.

## Before a command claim

Ordinary activation admission and the signed installed route check run before
preparation. Namespace-specific permission is sealed before any durable claim.
The existing backend retains immutable code readiness under the original
activation reservation, deadline and cancellation. Wasmtime canonicalizes the
input with the prepared component's actual parameter types, using the same
bounded decoder and encoder as invocation. Record order, tagged presence,
numeric representations and flags follow WIT types. Generic JSON serialization
cannot certify a command fingerprint.

The same readiness owner proceeds to materialization after scheduling; no
second repository lookup, compilation, Store or guest is introduced. A backend
without the authoritative codec refuses transaction admission. Codec scratch
and retained canonical bytes are prepaid from the original Phase 4 memory
ledger. The retained charge survives until actual input retirement, including
terminal observation. Canonicalization preserves the original node input limit
and every existing codec ceiling.

The HTTP exchange continues owning its input through activation cleanup and
bounded delivery. Disconnect handles retain its capacity until their last real
owner retires. A lost transport response cannot by itself authorize another
execution or classify an existing durable command as aborted.

Result routes use the existing reserved recovery lane and current result-read
policy. They create no activation or execution cell and do not require an old
guest execution generation to remain current. The lookup still matches the
installed tenant, namespace, incarnation, entity, companion and result policy.

Deferred HTTP installation uses the same provider and dispatcher. See
[signed deferred HTTP requirements](deferred-http-installation.md) for the
closed document and separate staging/dispatch permissions.

Related foundations: [optimistic state sessions](optimistic-state-sessions.md)
and the [single transaction writer fence](transaction-writer-fence.md).

## Current result delivery

The shared HTTP delivery owner can retain a current-purpose data fence. The
listener checks it inside every actual socket write and flush future poll,
including polls after a pending socket wakes. Revocation can stop the remaining
delivery; it cannot alter an already durable disposition or rerun the command.
The fence uses the original caller, publication, namespace, policy and deadline.
These final checks open no additional native view and consume no execution
ledger after its terminal accounting freezes.

Typed transaction delivery uses a fixed host-owned media type,
`application/vnd.latent.transaction-http.v1+json`, within the unchanged 256 KiB
response limit. It supplies `Cache-Control: no-store` and the existing browser
security headers. Historical guest headers, cookies and session material are
never copied into this response. HEAD retains the representation length while
sending no body. Portable tests verify ownership and denial between write polls;
real signed-node socket qualification remains required.
