# Transaction clients

The additive `latent.transaction-client.v1` models come from the exact required
StateService, TransactionService and DispatcherService descriptors. Their generated index retains
fully qualified Protobuf owners: transaction cursor paging is distinct from the
existing control-plane paging types. Existing stateless models and operations
remain supported.

## Read a committed view from an external client

Run the client as a separate process against an authenticated Linux node. Use
the original signed Java transactional aggregate fixture with a committed count
of `2`, the acknowledged namespace view token and a scoped invoke credential.
The companion contract is shared with the [Rust aggregate](../../examples/rust-capsules/transactional-aggregate/world.wit). The node runs the selected signed guest. Only the client
uses the language's native SDK transport.

1. Use the node's actual numeric `host:port` for `LSF_401_ENDPOINT` and set
   `LSF_401_TENANT`, `LSF_401_NAMESPACE` and `LSF_401_INCARNATION` from the
   installed namespace. Load `LSF_401_TOKEN` into the client process from its
   protected credential source.
2. Set `LSF_401_QUERY_MINIMUM_HEX` to the acknowledged commit's namespace
   view token encoded as hex. If the resulting count of `2` is from a later
   commit, set `LSF_401_QUERY_EXPECTED_HEX` to its independently observed view.
3. Run the fresh-query case for your SDK. Each source checks the real response
   against the committed view. Set `LSF_401_LIVE=1` for Go and TypeScript so the
   live cases execute. Set `LSF_401_MODE=query` for C and .NET to select the
   read-only mode in their shared live probe.

| Client | Maintained fresh-query entry point |
| --- | --- |
| Rust | `fresh_query_after_commit` in [the Rust live test](../../sdk/rust/tests/phase4_real_lost_response.rs) |
| C | `main` in [the C live probe](../../sdk/c/tests/phase4_real_lost_response.c) |
| TypeScript | [The Node transport fresh-query test](../../sdk/typescript-client/tests/network/phase4-real-query.test.mjs) |
| Go | `TestPhase4FreshQueryAfterCommitAgainstRealNode` in [the Go transport suite](../../sdk/go/transport/phase4_real_query_test.go) |
| Java | `dev.latent.sdk.transport.Phase4RealQuery` in [the Java transport suite](../../sdk/java-client/src/transportTest/java/dev/latent/sdk/transport/Phase4RealQuery.java) |
| C#/.NET | [The .NET live probe](../../sdk/dotnet/Latent.Sdk.Phase4RealLostResponse/Program.cs) |

With the SDK dependencies built for the selected client, run its command from
the repository root. The commands use the existing SDK build directories.

```bash
# Rust
cargo test --locked -p latent-sdk --test phase4_real_lost_response fresh_query_after_commit -- --ignored --exact

# C
cc -std=c11 -D_POSIX_C_SOURCE=200809L -Isdk/c/include sdk/c/tests/phase4_real_lost_response.c \
  target/c-sdk/liblatent.a target/c-sdk/libnghttp2.a -o target/c-sdk/phase4-real-query
target/c-sdk/phase4-real-query

# Node.js
npm --prefix sdk/typescript-client run build
node --test sdk/typescript-client/tests/network/phase4-real-query.test.mjs

# Go
(cd sdk/go && go test -count=1 ./transport -run '^TestPhase4FreshQueryAfterCommitAgainstRealNode$')

# Java, after building the transport test classes with the pinned JDK
java -ea -cp "sdk/java-client/build/test-classes:$(python3 sdk/java-client/tools/build.py classpath)" \
  dev.latent.sdk.transport.Phase4RealQuery

# .NET
dotnet run --project sdk/dotnet/Latent.Sdk.Phase4RealLostResponse
```

The fresh query carries an activation identity for observation and needs no
durable command key. Its typed result includes the authorized namespace
incarnation and exact view. The application payload's view must agree with
the host view, and the response carries neither a commit receipt nor effect
IDs. Close the client using its ordinary shutdown or disposal path.

For a later edit, retain the key version captured when the user read the
record and include it in the command's expected versions. If a command reply
is lost, start a fresh lookup in the original namespace using its operation,
entity when present, client key and current authorized result-read publication.
Use the retained receipt to decide whether a further action is possible.
After an older-history restore a previous view can be incompatible with the
new recovery epoch. Follow the recovery workflow before obtaining a new
business precondition. [Transaction recovery](../operations/transaction-recovery.md)

## Transport and recovery APIs

Rust exposes `latent_sdk::transaction::TransactionClient` on the existing
`network::RpcClient`. TypeScript exposes the same sixteen current operations on
`RpcClient` from `@latent/sdk/node`, with types under the pure `transaction` and
`transactionClient` exports. .NET exposes `Latent.Sdk.Transactions.ITransactionClient`
on the maintained `Latent.Sdk.Transport.BoundedClient`, returning owned
`TransactionResponse<T>` values or native cancellation/exception types with
independent `TransactionFailure` recovery metadata.
Go exposes them through the existing `transport.Client`, with context-aware
methods and independent `transaction.ClientFailure` recovery metadata. Java
implements `dev.latent.sdk.TransactionClient` on the existing transport
`RpcClient`, returning typed `CompletableFuture` responses or transaction
exceptions that preserve the original identity and any validated observation.
C exposes `latent_transport_transaction(owner)` and
`latent_transport_transaction_vtable()` from `<latent/transaction_client.h>`.
It uses the existing numeric-loopback HTTP/2 owner, explicit poll loop and
local call handles. Typed response, failure and recovery pointers are borrowed
through the completion callback; copy needed fields before returning.
The profile helpers construct the exact wire, host ABI and
preparation descriptor. These strings describe a request and confer no authority.
Every namespace/recovery request still needs its explicit current publication
selector, and the node checks the authenticated caller's current rights.

Each command carries the caller's original client key, canonical input format,
optional entity, stale-edit preconditions and explicit attempt fence. Responses
preserve committed, rejected, aborted, in-progress, unknown, expired and recovery
required states. Dropping a future, losing a response, gRPC `ABORTED`, local timeout
and cancellation never supply a durable abort fence. Callers retain the original
application request; lookup/inspection and any explicit new attempt are separate
calls. The SDK never resubmits a command or refreshes a generation/version.

All six clients retain a validated durable observation through a later transport, audit or
cleanup failure. Failure recovery metadata excludes the application payload;
the caller can explicitly recover the original result using its preserved
identity. Effects retain their separate dispatch disposition; a provider
acknowledgement does not prove the command's outcome or ordered dispatch.

Recovery snapshots are bounded before dispatch. Java, .NET and Node retain
independent copies of selectors, abort fences and stale-edit preconditions.
At most 128 expected-version entries can be submitted. An oversized collection,
text field or encoded request fails locally. Editing a caller-owned buffer
after submission cannot change the key or precondition used for recovery.
Go bounds the request graph before traversing its shape. The
[wire limits](../protocol/transactions.md#bounds-presence-and-encoding) also
apply to callers supplying their own transport.

Use `GetEffect` for the current disposition and `ListEffectHistory` to page
through retained attempts. Each page requires the original command and effect
association and current authorization. Browser callers have the narrower
[HTTP result projection](../development/transaction-http-v1.md#original-request-facts).

Effect management is explicit: `PlanEffectMutation` prepares finite checked data;
`MutateState` applies that exact plan and its original record version, policy
digest, action, reason and operation ID; `GetStateOperationReceipt` recovers the
original plan and receipt with a fresh current read publication. A prepared plan
remains an unknown mutation outcome and supplies no authority or provider proof.
The host rechecks current rights, the original row and physical attempt retirement.
Recovery accepts an expired historical plan when the recorded completion belongs
to its original finite window. Redrive scheduling, administrator declaration and
provider confirmation remain distinct typed receipt facts. Missing historical
record versions remain readable and cannot authorize a new plan.

Rust and Node transaction calls use the existing connection, credential, monotonically
decreasing deadline and physical request/response lease. The protocol ceiling is
2 MiB per request/response; configured client ceilings can be lower. Before native
conversion, owned model collections are bounded. Before Protobuf decoding, the
exact descriptor schemas reject malformed UTF-8, invalid full-width integers,
duplicate singular/oneof/map fields and excessive graphs. The original lease
reserves an additional 8 MiB graph allowance and 384 KiB recovery allowance;
active calls also share the existing configured byte ceiling. Capacity stays
charged until the original transport body retires. Shutdown closes admission
and waits for physical calls, sockets and executor work to retire. Node settles a
transaction await after the original HTTP/2 stream closes and returns its lease;
a later cancellation or audit error retains any validated durable observation.
Each failure's `transactionIdentity` contains the original key/preconditions and
its optional `observedTransaction` contains bounded receipt data without copying
the application body. An `AbortSignal` stops the local wait; explicit recovery
uses a fresh signal and the original identity.

.NET uses that same physical connection and reserved recovery admission, with
a 2 MiB wire ceiling, 8 MiB graph and 4096-node ceiling, bounded repeated fields
and metadata maps checked before native allocation. Its transaction deadline
is the minimum of the configured timeout, call timeout and original embedded
wall deadline. The canonical request and independent recovery data are copied
before the first asynchronous admission wait, so subsequent caller mutations
cannot replace a client key, attempt fence or stale-edit precondition. A later
audit failure retains validated bounded receipt data in `TransactionFailure`;
`CancellationToken` remains a local wait scope. Explicit recovery uses a new
live token and the original identity. C# `ulong` values and optional fields
retain their full width and presence.

Java preserves unsigned 64-bit values in `long` using unsigned comparisons and
formatting. Its immutable Protobuf request captures input, metadata and stale-edit
preconditions before dispatch; response buffers are read-only. The transaction
marshaller checks the exact descriptor before native parsing, including a shared
4096-node limit, 128-entry pages, 256 linked retention IDs, metadata limits,
duplicate fields/maps and strict UTF-8. The call uses the existing physical
owner, connection and finite executor/shutdown path. A cancelled future leaves
durable recovery explicit and uses a new live call for lookup.

C preserves unsigned generations and times in `uint64_t`. Its charged call arena
contains the original request snapshot and decoded response, with an 8 MiB
configured maximum. An exact descriptor walk checks wire fields before nanopb
allocation. Configured wire ceilings can be lower than the 2 MiB Phase 4 maximum;
the existing stateless method limits remain in force. Cancellation or stop closes
the shared physical connection before callbacks, and dispatched unfinished calls
remain unknown. Recovery stays explicit on a live owner.

The TypeScript package root exposes the pure `transaction` models, including
`bigint` uint64 values. Privileged RPC transport remains under the Node export.
Browser command/query/recovery execution must use the purpose-built authenticated
HTTP boundary rather than private management RPC.

Regenerate models with the repository's Buf, Rust and Go formatters. The
[toolchain manifest](../../tools/toolchain.toml) pins Buf 1.72.0, Rust 1.97.1 and Go 1.27.4.

```bash
python3 tools/transaction_client_models.py --check
python3 tools/transaction_client_conversions.py --check
python3 tools/transaction_client_rust_shapes.py --check
```

This source milestone includes six model sets and all six current transport facades.
The six transport suites include real-node command, rejection and lost-response
scenarios. Compare their executed evidence separately from [signed guest results](../testing/phase4-guest-progress-2026-11-09.md)
and the [browser reference application](../../examples/stateful-reference/README.md).
The full client matrix, backup/migration and packaged qualification remain
separate acceptance work.
