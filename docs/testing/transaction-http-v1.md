# Transaction application HTTP routes

The `transaction-http-v1` profile uses the node's shared HTTP listener for a
direct command, a fresh read-only query, or an authorized original-result lookup.
All six transaction guest profiles use the same canonical WIT value format. A
guest exports its ordinary typed operation and does not implement another HTTP
listener or a synchronous service hop inside the transaction.

A route fixes its tenant, publication, deployment generation, operation,
namespace/incarnation, schema, signed companion digest, binding, result policy,
and optional entity. The corresponding descriptor must already be installed
from the admitted package's signed `transaction-binding.json` asset. Configuration
describes these links; the current publication, namespace and purpose-specific
policy must still authorize the request. Request headers cannot change them.

## Requests

| Route mode | Method and input | Command identity and state conditions |
| --- | --- | --- |
| `command` | POST, PUT, PATCH or DELETE; a nonempty bounded canonical WIT body with `application/vnd.latent.wit-values.v1+json`; no URL query | Exactly one `Idempotency-Key`. Optional `If-Match` is a quoted canonical standard-base64 67-byte `SV2` key token for the route's fixed `preconditionKey`. |
| `query` | GET or HEAD without a body or content type; optional single `input=` URL-safe base64 value, without padding, bounded to 8192 decoded bytes; absence means `[]` | `Idempotency-Key` cannot turn the read into a mutation. Optional `If-State-View` is a canonical standard-base64 complete 67-byte `NV2` view token. |
| `result` | GET without body, content type, URL query or state conditions | Exactly one original `Idempotency-Key`. This path performs original-result lookup and does not prepare or run the original mutating guest. |

Command IDs contain 1–128 ASCII letters, digits, dots, underscores or hyphens.
Duplicate identity/condition/retry fields and ambiguous encodings reject.
Commands retain the canonical prepared input, original method and normalized
business path, fixed operation/entity and original expected versions as their
fingerprint. Authentication, cookies, trace context and transport deadlines are
excluded. Changing credentials never changes an existing command's caller
scope; changing input or operation does not silently reuse its result.

An explicit retry additionally requires a bounded `Command-Retry-Key` and
`Command-Abort-Fence`. The latter is standard-base64 of the closed JSON object
returned as `abort-fence`, whose `owner-fence` is standard-base64 of the original
32-byte server-issued proof. The common command owner verifies the original
aborted attempt and preserves its source and fingerprint. A timeout, lost socket,
5xx or client-created proof supplies no retry authority.

## Results and delivery

Responses are bounded JSON with `profile`, `disposition`, `representation`,
original command/attempt identity, complete `state-view`, original effect IDs,
original result horizon, delivery failure and abort evidence where available.
The `result` contains canonical typed bytes as `body-base64`, their media type,
and an optional declared error code/message. Framework metadata, historical
credentials and arbitrary response headers or cookies are excluded.

| HTTP status | Durable observation |
| --- | --- |
| 200 | Committed command or fresh query. |
| 202 | Original command still in progress; this is a finite observation. |
| 422 | Durable business rejection or a read-only declared error. |
| 409 | Conflict; an explicit aborted-command envelope includes its real retry fence. A bare conflict has no retry authority. |
| 503 | Recovery required; no automatic resubmission authority. |
| 410 | Original retained result expired, with an authorized receipt only. |
| 404 | Authorized lookup found no original command. |
| 401 / 403 | Authentication or current-purpose authorization refused. |

HTTP status and durable disposition remain separate. A terminal `receipt-only`
representation never promises the application's body. `status-only` does not
promise completion. Queries create no durable command, result, inbox or effect
row and carry the token from their actual single native view.

Before the single commit owner publishes business changes, the HTTP result codec
checks the replayable media type, 128 KiB payload bound and finite declared error
fields. The complete response fits the shared 256 KiB envelope. Unsupported
required replay forms reject before commitment.

Transaction replies use no-store and the existing host-owned browser, proxy,
origin/Fetch Metadata, CSP and cookie protections. Static asset grants do not
grant application access. Each actual nonblocking socket/TLS write poll rechecks
the original cancellation/deadline and current publication, namespace and result
policy. A disconnect after commitment preserves the original disposition. All
remaining buffers and native response owners retire before admission is refunded.

## Qualification scope

The shared ingress mapping and codec tests establish structural bounds and
credential exclusion. Linux ownership tests establish physical state and HTTP
effect primitives. These checks do not by themselves establish final signed
Java execution, application browser behavior or a full six-guest campaign.
Those require the exact components and current policy through this installed
node path; compiler receipts alone are insufficient.
