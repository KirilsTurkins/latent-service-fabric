# Direct transaction HTTP binding v1

The `transaction-http-v1` application profile uses the shared HTTP ingress and
the normal activation owner. Its fixed target is the selected deployment,
publication, contract and function. It does not create a cross-service
transaction through a stateless adapter's synchronous child call.

This checkpoint defines route/request ownership and prepared input
canonicalization. Standalone state composition, response/result delivery and
real signed Java socket qualification are required before the profile is ready
for application use. Portable mapping tests are not evidence of durable guest
execution.

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

## Before a command claim

The existing backend first retains immutable code readiness under the original
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

Related foundations: [optimistic state sessions](optimistic-state-sessions.md)
and the [single transaction writer fence](transaction-writer-fence.md).
