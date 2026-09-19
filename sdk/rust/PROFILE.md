# Rust common client profile adapter

With the default `transport` feature, `network::RpcClient` implements the
[common eight-operation `management::ClientProfile`](../profile/README.md).
The existing `LatentClient` implementation and generated management methods
remain available. Import only the desired trait, or use fully qualified trait
calls when both invocation interfaces are in scope.

```rust
use latent_sdk::{management, network::RpcClient};

async fn recover(
    client: &RpcClient,
    operation_id: String,
) -> Result<management::ClientResponse<management::GetPolicyOperationResponse>, management::ClientFailure> {
    management::ClientProfile::get_policy_operation(
        client,
        management::GetPolicyOperationRequest { operation_id },
        management::CallOptions { timeout_millis: Some(1000) },
    ).await
}
```

The facade calls the existing private `RpcClient::unary` with generated RPC
clients, not a JSON bridge or a second channel. Clones share the same lazy
connection, finite call/message leases, socket and tracked executor owners.
`shutdown` is the existing client shutdown; a dropped facade future stops its
local wait and does not send Cancel, prove guest cleanup or roll back a policy.

## Conversion and boundaries

All eight operations use the complete profile DTOs, including raw u32 priority,
optional budget/identity/selector fields, full-width u64 values and redacted
provider inspection. Typed `From` conversions move fields between the portable
models and generated protobuf messages. Reverse conversion of response oneofs
uses `TryFrom` and rejects contradictory members rather than choosing one.
Absent, empty and zero values are never normalized by conversion. Public
`management` remains available without the transport feature.

The executable boundary rejects invalid required identities and generation
preconditions before dispatch, preserves their bounded recovery IDs in errors,
and checks returned identity/receipt consistency. Publication IDs remain distinct
from component digests; malformed present publication IDs fail response validation.
Unknown numeric management/cancellation enums survive as raw i32 values, never
as a known success disposition. Unsupported invocation phase/terminal/platform
strings fail explicitly with bounded `unsupported_wire_value` evidence and any
already-received valid activation ID.

Policy pages require a positive size through the server's hard ceiling 32 and
tokens no larger than 117 bytes. Lower configured server limits remain server
decisions. Capability pages preserve absent/zero as the server default 128,
accept explicit sizes through 128, and bound tokens to 160 bytes. No page is
automatically drained or restarted. The facade applies the policy and capability
encoded-size limits from the common profile, additionally capped by client
configuration. Capability revision/usage absence is retained, never synthesized
into a grant, zero usage or a principal claim.

`CallOptions` starts one absolute local deadline when the facade method creates
its future, before polling, conversion, connecting or dispatch. Absent timeout
uses the configured finite default; zero fails without dispatch. The duration
must fit the checked signed-millisecond/monotonic-clock representation and is
capped by the configured RPC timeout. The invocation's separate absolute Unix
deadline can only shorten that deadline; it remains unchanged on the wire.
Response validation/conversion does not restart the clock.

## Recovery and audit

The rich common error retains raw RPC status, bounded typed platform details,
dispatch/outcome knowledge, recovery identity and independent audit facts. Legacy
message/retryable errors are not a substitute. `ApplyPolicy` requires a supplied
`expected_generation`, including explicit zero for create, and a caller-known
operation ID. Neither this adapter nor the model generates IDs or retries.
A missing operation receipt, including a NotFound recovery RPC, remains Unknown.

An observed valid receipt is independent of audit availability. Known audit
header text maps to its existing numeric `AuditAckStatus` and is also retained
as `audit_status`. The independent optional u64 `audit_attempt_sequence` retains
the exact sequence on both response metadata and failures, including when future
bounded status text has no recognized numeric tag. Unknown header text leaves
`audit_ack` absent: no `UNSPECIFIED`, Durable or other enum is fabricated. Known
headers retain `AuditAck` as well as both independent raw fields. Absent audit metadata
stays absent. A malformed audit header can fail decoding while the independently
validated receipt outcome and operation identity remain observed/recoverable.
Already-known identities survive response-validation errors.

## Bounded validation

```text
python sdk/rust/src/network/profile/generate_conversions.py --check
cargo test -p latent-sdk --locked --lib network::profile::vectors -- --nocapture
cargo test -p latent-sdk --locked --test profile_transport
cargo test -p latent-sdk --locked --no-default-features
cargo clippy -p latent-sdk --no-deps --locked --all-targets -- -D warnings
```

The conversion generator reads the authoritative shared profile and emits
typed Rust conversions plus 49 shared cases that encode/decode real protobuf
messages. It requires the pinned `rustfmt`; `--patch` emits an `apply_patch`
update. There is no runtime JSON serialization and no independent wire schema.

The controlled TCP tests cover all eight facade calls plus the legacy interface
on one channel; page defaults/limits; absence and full-width fields; unknown
enums and unsupported strings; pre-dispatch and post-dispatch deadlines; local
drop/capacity/explicit Cancel; mutation recovery with explicit replay; typed RPC
errors; and independent known/unknown audit facts. Peer teardown and owner checks
are finite. They are not tiny-node, provider or authorization acceptance tests;
those remain with the parent Rust transport delivery and its real-node suite.

The audit-sequence correction is shared model commit `e4096670` and adapter
commit `d8b0636a`. Validation on Windows/Rust 1.97.1 with parent transport
`2cae79d5` passes 49 protobuf cases, the raw-audit conversion unit test, all ten
parent TCP tests, ten of eleven profile TCP tests, targeted formatting,
regeneration and strict SDK-only Clippy. Unknown `future-state` plus a maximum
attempt survives an RPC failure without fabricating an acknowledgement.

The remaining profile TCP test deliberately fails: the parent audit parser
rejects `future-durable-v2` because it permits only lowercase ASCII and dashes,
then loses the independently valid attempt sequence. The adapter retains the
raw status, observed receipt outcome and recovery identity, but cannot recover
an attempt omitted by the parent. Accepting bounded opaque status tokens,
including digits, remains a parent-owned `network/error.rs` integration
dependency. The regression is neither ignored nor weakened; the full adapter
suite is not yet green on that parent head.

No workflow, package manifest, shared SDK runner or other transport
implementation file is changed beyond the additive `mod profile;`. Parent
integrates adapter code/docs into #228; no separate adapter PR or issue closure
is requested. Provider-backed real-node qualification remains with the shared
runner and parent participants, not these controlled TCP tests.
