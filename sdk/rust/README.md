# latent-sdk

External Rust client SDK for standalone invocation, management and additive transaction/dispatcher operations. Transport-neutral typed models are always available; the default `transport` feature adds a reusable bounded generated-RPC client.

`RpcClient` owns a shared lazily opened channel, finite calls/tasks/sockets and original call deadlines. It does not configure node providers, install application grants or execute guest code inside the client process.

## Responsibilities and architecture

| Source | Responsibility |
| --- | --- |
| [src/lib.rs](src/lib.rs) | Feature-gated client module exports. |
| [src/management.rs](src/management.rs) | Typed management and eight-operation ClientProfile contract. |
| [src/network.rs](src/network.rs) | RpcClient construction, lazy connection, limits, usage and physical shutdown. |
| [src/network/profile.rs](src/network/profile.rs) | Managed profile transport behavior and checked associations. |
| [src/network/transaction.rs](src/network/transaction.rs) | Additive Phase 4 calls on the same owner/channel. |
| [src/transaction/mod.rs](src/transaction/mod.rs) | Command/query/recovery client contracts preserving original business identity. |
| [examples/provider_client.rs](examples/provider_client.rs) | Concrete invocation/status/cancel consumer of the SDK. |
| [examples/provider_workflow.rs](examples/provider_workflow.rs) | Finite shared real-node client qualification participant. |

## Execution and ownership

1. Construct explicit endpoint/tenant/credential/limit configuration; construction starts no I/O.
2. Reserve a bounded call owner and connect lazily under its original monotonic deadline.
3. Send one typed operation, validate response shape and associate identities before exposing results.
4. Keep mutation knowledge, audit metadata and transport failure separate. Explicit status/recovery/cancel uses the retained identity.
5. Close admission and await actual local calls/tasks/sockets during shutdown; local retirement does not certify remote guest/provider cleanup.

## Integration boundaries

Use `default-features = false` for transport-neutral interfaces. A controlled TCP/gRPC peer proves codec/transport behavior, not production transaction execution. The maintained provider examples and source-bound qualification records establish narrower scopes; broader signed-node/client acceptance remains tracked separately. Dropping an invocation future is not application cancellation or permission to repeat a mutation.

## Dependencies and build

Direct workspace dependencies: [latent-core](../../crates/latent-core/README.md), [latent-rpc](../../crates/latent-rpc/README.md) (optional).

Cargo features (the manifest owns their exact expansion):

| Feature | Enables |
| --- | --- |
| `default` | `transport` |
| `transport` | `dep:latent-rpc`, `dep:prost`, `dep:tokio`, `dep:tonic`, `dep:tonic-prost`, `dep:http`, `dep:http-body`, `dep:hyper`, `dep:hyper-util`, `dep:tower`, `dep:zeroize` |

Use [Cargo.toml](Cargo.toml) for external dependencies, target gates and test/build edges; [the workspace manifest](../../Cargo.toml) and [the toolchain guide](../../docs/development/toolchain.md) own current pins. Dependency presence does not install a runtime service.

## Tests and verification

The [package entry point](src/lib.rs) and the module links above are the source map. [The workspace package guide](../../docs/development/workspace-packages.md) explains feature/target selection, generated inputs and the registered test workflow.

Inspect a registered suite from the repository root without building or running it:

```sh
python3 tools/test.py explain --suite latent-sdk.lib.latent-sdk
```

Use `list --output json` to find the remaining package targets. Follow the suite's recipe, platform and prerequisites for preparation, discovery and execution; a registration or compile-only check is not a passing execution/qualification result.

Representative source tests (not a complete coverage inventory):

- [`raw_audit_sequence_survives_without_any_invented_acknowledgement`](src/network/profile/metadata.rs)
- [`shared_vectors_roundtrip_through_actual_protobuf`](src/network/profile/vectors.rs)
- [`configuration_is_explicit_bounded_redacted_and_does_not_start_io`](src/network/tests.rs)
- [`audit_metadata_preserves_full_width_and_rejects_ambiguous_presence`](src/network/tests.rs)

Integration targets: [tests/client_profile_lifetime.rs](tests/client_profile_lifetime.rs), [tests/client_profile_vectors.rs](tests/client_profile_vectors.rs), [tests/network_transport.rs](tests/network_transport.rs), [tests/profile_transport.rs](tests/profile_transport.rs).

## Related documentation

- [Bounded Rust RPC client](../../docs/reference/rust-client.md)
- [Transaction clients](../../docs/development/transaction-clients.md)
- [Installed transaction RPCs](../../docs/development/installed-transaction-rpc.md)
- [WIT value payloads](../../docs/protocol/wit-values.md)
- [Configure standalone providers](../../docs/reference/standalone-providers.md)
- [Workspace package index](../../crates/README.md)
- [Architecture index](../../ARCHITECTURE.md)

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

Both use the [supported WIT-value framing](../../docs/protocol/wit-values.md),
with `application/vnd.latent.wit-values.v1+json`, a three-value argument array
and a decimal-string `u64` result. They are not the older generated test probes.

[Standalone provider configuration](../../docs/reference/standalone-providers.md)
is available for HTTP and local blobs. The default node grants neither capability;
configure the provider, policy, binding and deployment before using this example.

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
The retained shared qualification run passed all 18 assertions with nine admitted
activation IDs and four physically closed upstream holds; PR #366 retains
the source identities and independent clean node/provider shutdown receipts.
Current policy RPCs emit no audit acknowledgement, so this participant asserts
absence rather than inventing durability. It uses an explicit five-second RPC
limit matching the node profile. Controlled peers separately verify audit
metadata and malformed response handling. These are not installed-bundle,
browser or whole-process RSS isolation claims.

The registered tests include controlled TCP/gRPC peers. Those peers verify wire and local ownership behavior; use the real-node participant and its source-bound records for provider execution evidence.
