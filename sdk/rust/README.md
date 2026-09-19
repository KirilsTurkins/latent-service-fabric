# Rust client

`latent-sdk` includes a reusable generated-RPC client, enabled by the default
`transport` feature. The [client contract](../../docs/reference/rust-client.md)
defines endpoint/auth restrictions, message/owner limits, original deadlines,
typed outcomes, operation recovery and physical shutdown. Build with
`--no-default-features` for the transport-neutral models only.

## Invoke HTTP and blob guests

`provider_client` calls an **already admitted and deployed guest**. It does not
make an HTTP request, access a blob store directly, configure a provider or
receive provider credentials. The node operator must separately configure
the shared provider and matching policy/binding, package/admit the maintained
guest, and deploy its route for the client's tenant:

- [Maintained Rust HTTP guest](../../tools/toolchain-smoke/examples/guest_http/component.rs):
  `tests:http/api@1.0.0`, `run(0, URL, "0")`, bounded GET through the guest's grant.
- [Maintained Rust blob guest](../../tools/toolchain-smoke/examples/guest_blob/component.rs):
  `tests:local-blobs/api@1.0.0`, `run(0, "", "0")`, bounded write/seal/read/close.

Both use the [guest SDK's supported WIT-value framing](../../docs/component-development/guest-sdk.md),
with `application/vnd.latent.wit-values.v1+json`, a three-value argument array
and a decimal-string `u64` result. They are not the older generated test probes.

Standalone provider configuration and real-node qualification are part of
#226/#228; the ordinary default node does not grant either capability. These
commands do not claim that prerequisite installation or qualification has
already happened.

Use Linux x86-64 for the example's existing protected-file reader. Provision
the node's **client bearer token**, with no trailing newline, in an owner-only
regular file inside a protected directory. Do not pass its value on the
command line, store it in the repository, give it to a guest, or substitute a
provider credential. Symlinks, unsafe ownership/permissions and unsupported
platforms fail closed. The client endpoint must be numeric loopback.

```sh
cargo build -p latent-sdk --example provider_client --locked
target/debug/examples/provider_client 127.0.0.1:9080 tests \
  /home/operator/.config/latent/client-token http-call-001 http generic guest-http \
  http://localhost:8080/allowed
target/debug/examples/provider_client 127.0.0.1:9080 tests \
  /home/operator/.config/latent/client-token blob-call-001 blob generic guest-blob
```

Supply the actual deployed service/route IDs and policy-approved upstream URL.
Choose a fresh activation ID for a new invocation and retain it before sending.
The output is bounded JSON containing the outcome class, numeric guest result,
resource consumption and local owner-retirement acknowledgement, not arbitrary
guest output, secrets or server error detail. Blob success returns the decimal
string `4`; HTTP returns `status + 1000 * body_length` or its frozen guest
error variant. `succeeded` means the RPC delivered an application result;
applications must still check that guest result, not assume all values are a
successful HTTP operation. Counters and `u64` guest values retain full width.

If an invocation response is lost, do **not** run the invoke command again:

```sh
target/debug/examples/provider_client 127.0.0.1:9080 tests \
  /home/operator/.config/latent/client-token http-call-001 status
target/debug/examples/provider_client 127.0.0.1:9080 tests \
  /home/operator/.config/latent/client-token http-call-001 cancel
```

The example uses the SDK rather than CLI internals. An explicit cancel is
separate from dropping the local invocation wait. A successful local shutdown
does not certify guest cleanup; observe the node's retained terminal state
and its provider ownership where required. An absent retained activation is
not evidence that it never ran. There is no retry or background polling loop.

## Shared real-node participant

`examples/provider_workflow.rs` implements the six-language qualification
contract using this SDK's eight-operation `management::ClientProfile` facade.
Build it with `cargo build -p latent-sdk --example provider_workflow --locked`.
The shared operator runner supplies an owner-only `--config` file on Linux
x86-64, a protected client credential, three signed maintained guest targets
and a private HTTP-provider rendezvous directory. The participant does not
bootstrap authority, call CLI internals or receive provider credentials.

Its finite scenario checks provider results, distinct declared/platform/RPC
failures, tenant/authentication rejection, bounded pages, provider inspection,
mutation receipts, explicit replay, generation conflicts and response limits.
Four actual held provider requests separate local waiter drop, application
Cancel, original deadline and shutdown. Recovery uses retained identities;
shutdown waits for actual local call/task/socket owners. The operator runner
independently checks terminal activations and provider/node reclamation.
This executable is not by itself an execution receipt: actual-node results
are retained separately by the shared qualification run.

## Checks

```sh
cargo test -p latent-sdk --all-targets --locked
cargo test -p latent-sdk --no-default-features --locked
cargo clippy -p latent-sdk --all-targets --locked --no-deps -- -D warnings
```

The transport suite uses a controlled real TCP/gRPC peer. It verifies wire and
ownership behavior but does not stand in for real LSF provider execution.
