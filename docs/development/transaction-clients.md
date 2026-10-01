# Transaction clients

The additive `latent.transaction-client.v1` models come from the exact required
StateService and TransactionService descriptors. Their generated index retains
fully qualified Protobuf owners: transaction cursor paging is distinct from the
existing control-plane paging types. Existing stateless models and operations
remain supported.

Rust exposes `latent_sdk::transaction::TransactionClient` on the existing
`network::RpcClient`. TypeScript exposes the same twelve core operations on
`RpcClient` from `@latent/sdk/node`, with types under the pure `transaction` and
`transactionClient` exports. The profile helpers construct the exact wire, host ABI and
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

Rust retains a validated durable observation through a later transport, audit or
cleanup failure. Failure recovery metadata excludes the application payload;
the caller can explicitly recover the original result using its preserved
identity. Effects retain their separate dispatch disposition; a provider
acknowledgement does not prove the command's outcome or ordered dispatch.

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

The TypeScript package root exposes the pure `transaction` models, including
`bigint` uint64 values. Privileged RPC transport remains under the Node export.
Browser command/query/recovery execution must use the purpose-built authenticated
HTTP boundary rather than private management RPC.

Regeneration uses pinned Buf 1.72.0, Rust 1.97.1 formatting and Go 1.27.1 formatting:

```bash
python3 tools/transaction_client_models.py --check
python3 tools/transaction_client_conversions.py --check
python3 tools/transaction_client_rust_shapes.py --check
```

This source milestone includes six model sets and the Rust and Node transport facades.
The other four maintained transport facades, dispatcher/backup/migration full
profile operations, separate-node six-client scenario matrix and browser HTTP
execution remain outstanding. Generated model checks, codec tests and compiler
checks do not qualify signed guest execution or real external-client execution.
Issue #401 stays open until those independent acceptance gates pass.
