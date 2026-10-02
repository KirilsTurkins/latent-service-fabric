# Transaction client node campaign

The six maintained SDKs include a finite participant for exercising the frozen
sixteen transaction, state and dispatcher operations against a separately owned
Linux node. Each participant calls the existing SDK transport, shares one client
channel across its steps, and explicitly shuts that owner down. The program does
not install a namespace, issue a permission, sign a package or substitute a peer
for the node.

These are source fixtures. Their native builds and the complete authenticated
standalone scenario matrix still require qualification at the tested revision.
The eight Python fixture-vector cases establish file encoding and explicit
recovery rules; they do not establish guest execution, durable commit, caller
authorization or physical retirement on a node.

## Maintained entry points

Use the exact pinned toolchains and existing SDK build recipes. Compilation and
execution are separate phases; the process adapter never builds implicitly.

| Client | Source | Build command and working directory | Prepared program |
| --- | --- | --- | --- |
| Rust | [`transaction_node_workflow.rs`](../../sdk/rust/examples/transaction_node_workflow.rs) | `cargo build -p latent-sdk --example transaction_node_workflow --locked` at repository root | `target/debug/examples/transaction_node_workflow` |
| TypeScript | [`transaction-node-workflow.mjs`](../../sdk/typescript-client/examples/transaction-node-workflow.mjs) | `npm ci && npm run build` in `sdk/typescript-client` | `node sdk/typescript-client/examples/transaction-node-workflow.mjs` at repository root |
| Go | [`transaction_node_workflow_linux_test.go`](../../sdk/go/transport/transaction_node_workflow_linux_test.go) | `go test -c ./transport -o transaction-node-workflow` in `sdk/go` | `sdk/go/transaction-node-workflow` at repository root |
| C | [`transaction_node_workflow.c`](../../sdk/c/examples/transaction_node_workflow.c) | `python3 sdk/c/tools/build.py --check-generated` at repository root | `target/c-sdk/transaction-node-workflow` |
| Java | [`TransactionNodeWorkflow.java`](../../sdk/java-client/src/example/java/dev/latent/sdk/transport/TransactionNodeWorkflow.java) | `python3 sdk/java-client/tools/build.py build` at repository root | `java -cp "$CLASSPATH" dev.latent.sdk.transport.TransactionNodeWorkflow`, using the exact output of `python3 sdk/java-client/tools/build.py classpath` |
| .NET | [`TransactionNodeWorkflow.cs`](../../sdk/dotnet/Latent.Sdk.Transport.Tests/TransactionNodeWorkflow.cs) | `dotnet build sdk/dotnet/Latent.Sdk.Transport.Tests/Latent.Sdk.Transport.Tests.csproj` at repository root | `dotnet sdk/dotnet/Latent.Sdk.Transport.Tests/bin/Debug/net8.0/Latent.Sdk.Transport.Tests.dll` |

Run those commands on the maintained Linux x86-64 profile. The build table is an
explicit qualification recipe; none of these new participant builds is claimed
as complete by this source milestone. Retain each actual tool version, source
revision, build log and executable digest before starting its lane. The existing
SDK dependency locks and tool pins still apply.

The Go test executable and .NET test assembly select this mode only with the
explicit `--node-fixture` argument. Their normal invocations continue to run all
existing tests. No ignored or environment-skipped native case replaces this
campaign.

## Original request and process ownership

Every prepared program accepts these five arguments:

```text
--node-fixture http://127.0.0.1:PORT TENANT /private/caller-token /private/new-session
```

The node must already be running with its real protected store, signed admitted
publication, current policy, namespace and trusted transaction installation.
The fixture owner supplies the authenticated token in a bounded private file,
never as a command-line argument or in diagnostic output. A fresh private
directory retains the original protobuf request and owned responses. The shared
adapter creates that directory with mode `0700` and files with mode `0600`.

[`transaction_node_participant.py`](../../tools/transaction_node_participant.py)
uses the authoritative current and stateless descriptor-derived contracts for
its fixture files. Each SDK performs its own maintained DTO conversion and
response validation. Unsigned 64-bit fixture values use canonical decimal
strings; binary values remain bytes. An absent field, present zero, empty bytes
and a false oneof precondition remain distinct. Unknown, duplicate or
contradictory fixture fields fail closed.

The owner sends one bounded line after saving `ID.request.pb`:

```text
invoke_command ID 5000 -1
lookup_command RECOVERY_ID 5000 -1
close
```

The operation uses snake case and must belong to the frozen sixteen operations.
IDs contain 1–64 ASCII letters, digits, underscores or hyphens and cannot repeat.
The last two numbers select an original call timeout of 1–5000 milliseconds and
an optional local cancellation delay of 0–5000 milliseconds; `-1` disables that
local cancellation. Each process accepts at most 32 calls under one original
120-second lifetime. The parent process owner imposes that deadline while
waiting for input and owns bounded final cleanup.

`ready` and `done ID` are synchronization messages. Actual responses are copied
to `ID.response.pb`. Any validated durable observation retained through a client
failure is saved separately as `ID.command.pb`, `ID.effect.pb` or the matching
receipt type. `ID.result.json` retains only status, failure category, gRPC status
and whether the SDK observed dispatch. Raw exception strings, credentials and
HTTP bodies are excluded from these diagnostics.

The parent first waits for normal SDK shutdown, then positively retires the
original process group. It accepts completion only with process exit zero and
the actual `cleanup.json` reporting clean client ownership. Forced process
retirement after a failure does not become a successful client cleanup receipt.

## Shared scenario obligations

Use the same case family for all six clients. Actual current policy and original
host-owned controls must provide caller changes, read revocation, node restart,
lost-response injection and physical attempt retirement. Fixture input values
and a parsed abort fence cannot supply those permissions or proofs.

The retained original request is the source of command key, input and stale-edit
preconditions for replay and recovery. Transport loss or local cancellation
never causes an automatic command replay. A separate lookup observes the durable
outcome. The explicit-attempt helper copies an actually observed durable
`Aborted` inspection and its exact command, attempt, transaction and owner fence;
the host must still prove original physical retirement and accept the attempt
CAS. A success, rejection, expiry, unknown result or uncertain abort cannot
produce that retry request.

After a successful command, verify a fresh query, pending effect and result
receipt. Also verify rejection after later state change, unchanged execution
count on replay, stale edit refusal, wrong tenant/caller refusal, denied result
read after revocation, newly granted current read authority, body expiry with
retained metadata, bounded continuation on short history pages, restart recovery
and cancellation before and after commit. Each lane records its source/profile,
prepared executable and component identities, actual node observations and
positive client/node/process cleanup. Privileged management RPCs stay in the
Node client surface; browser query/command transport qualification is separate.
