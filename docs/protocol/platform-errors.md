# Platform error model

Component domain errors are declared by each WIT contract. Infrastructure failures use stable platform codes.

| Code | Meaning | Generally retryable |
|---|---|---|
| `unavailable` | Required node, provider, backend, or route temporarily unavailable | Sometimes |
| `deadline-exceeded` | Activation deadline elapsed | No automatic write retry |
| `cancelled` | Caller or platform requested cancellation | No |
| `resource-exhausted` | CPU, memory, host-call, payload, queue, or quota limit exceeded | After policy change or backoff |
| `permission-denied` | Principal or capsule lacks a grant | No |
| `unauthenticated` | Identity could not be established | After reauthentication |
| `invalid-argument` | Envelope or platform call is invalid | No |
| `not-found` | Service, release, state, effect, or capability not found | Usually no |
| `already-exists` | Requested identity or activation already exists | Usually no |
| `incompatible-contract` | Consumer and provider contracts cannot bind | No |
| `state-conflict` | Optimistic transaction conflict | Only when declared safe |
| `dependency-failed` | Child invocation or capability operation failed | Depends on cause |
| `guest-trap` | Guest code trapped | Only under explicit policy |
| `corrupt-artifact` | Digest, validation, or preparation failure | No until artifact changes |
| `route-unavailable` | No eligible revision or node | Sometimes |
| `admission-rejected` | Quota, overload, deadline, policy, or placement rejection | Depends on reason |
| `internal` | Fabric defect or uncategorized failure | Conservative |

Every platform failure carries a stable code, human-readable message, explicit retryability hint, and structured details. The hint does not override operation-level idempotency rules.

`latent-rpc::platform_error` is the canonical Rust/domain-to-Protobuf conversion seam for both invocation and control-plane `PlatformError` messages. It preserves ordered detail items and every detail field exactly. Unknown wire codes return `UnknownPlatformErrorCode`; they are never coerced to `internal` or another known meaning.
