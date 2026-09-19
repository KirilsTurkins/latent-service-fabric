# Bounded Java client

`dev.latent.sdk.transport.RpcClient` implements both
`Management.ClientProfile` and the existing `CompletionStage`-based
`LatentClient`. The eight executable operations are Invoke, Cancel,
GetActivation, GetPolicy, ListPolicies, ListCapabilities, ApplyPolicy and
GetPolicyOperation. This is a native HTTP/2 gRPC client, not a CLI subprocess,
JSON bridge, guest-language runtime or direct provider client.

The [shared profile](../profile/README.md) defines the operation/model contract.
`src/main/java` remains the dependency-free model surface; `src/transport/java`
is the executable facade. Generated protocol classes remain in the separate
`latent.invocation.v1` and `latent.control.v1` namespaces under `build/generated`.
Their existence does not make additional management RPCs supported client APIs.

## Clean build

The target/runtime toolchain is Java 21; qualification uses Temurin
21.0.11+10 and Python 3.13. Locked native generators support Linux x86-64 and
Windows x86-64. Windows development tests also run on JDK 25 with `--release 21`;
that is not evidence of a Windows JDK 21 qualification. No Android, remote-node,
TLS/mTLS, browser or Java guest-runtime profile is claimed.

From the repository root:

```sh
python3 sdk/java-client/tools/build.py test
python3 sdk/java-client/tools/build.py build
```

Use `python` in PowerShell. Outputs and caches stay inside
`sdk/java-client/build/`; production classes and test classes have separate
directories. Build creates `latent-java-client.jar` with a fixed archive
timestamp and a manifest referencing only the locked `deps/` JARs. Keep those
dependencies beside the JAR. `tools/build.py classpath` also prints the explicit
class directory/dependency path for embedding. No Gradle or Maven installation
is needed. The Gradle
project also exposes `semanticTest` and `transportTest`, both included by
`check`, and runs the same locked preparation before Java compilation.

The flat [dependency lock](dependencies.lock.json) pins every dependency and
both native generators by HTTPS Maven Central path, exact size and SHA-256:
gRPC-Java 1.84.0 and protobuf/protoc 3.25.9. A missing artifact is downloaded
with a finite timeout/size; a mismatching cached artifact is rejected, not used
or silently replaced. Builds do not resolve version ranges or invoke remote
Gradle plugins. Generation uses the repository's authoritative protobuf files.
The typed bridge generator also rejects shared-contract drift from those files.

```sh
python3 sdk/java-client/tools/generate_bridge.py --check
python3 sdk/java-client/tools/generate_bridge.py --patch
python3 sdk/java-client/tools/lock_dependencies.py
```

The last two commands emit reviewable `apply_patch` updates; they do not rewrite
tracked files. Updating dependency versions is an explicit lock-review task.
Upstream API/dependency references are the pinned
[gRPC-Java sources](https://github.com/grpc/grpc-java/tree/v1.84.0) and
[published protobuf dependency](https://repo.maven.apache.org/maven2/com/google/protobuf/protobuf-java/3.25.9/protobuf-java-3.25.9.pom).

## Configure and call

```java
import dev.latent.sdk.Management;
import dev.latent.sdk.transport.ClientConfig;
import dev.latent.sdk.transport.RpcClient;
import java.util.Optional;

try (var client = new RpcClient(ClientConfig.loopback(endpoint, tenant, clientToken))) {
    var response = client.getPolicyOperation(
            new Management.GetPolicyOperationRequest(callerKnownOperationId),
            new Management.CallOptions(Optional.of(3000L))).get();
    var receipt = response.value().receipt();
}
```

Endpoint, tenant and bearer token are explicit. Only `http://127.x.x.x:PORT`
and `http://[::1]:PORT` are accepted, without userinfo, path, query or fragment.
The numeric address is passed directly to gRPC: no DNS resolver, environment
proxy, remote listener or credential discovery is used. Credentials occur only
in the authorization header; configuration/client/error descriptions are
redacted. No principal or provider credential is inserted into a request DTO.
Java strings are GC-managed; this API does not promise secret zeroization.

`ClientConfig` also has an explicit bounded constructor:

| Parameter | Default helper / hard bound |
| --- | --- |
| Concurrent accepted calls | 32 / 1..128; overload fails locally, no admission queue |
| Encoded request/decoded response | 1 MiB each / 1 byte..4 MiB each |
| Default RPC timeout | 30 seconds / 1..30000 milliseconds |
| TCP connect cap | 5 seconds / positive and no greater than RPC default |
| Close timeout | 5 seconds / 1..10000 milliseconds |

The shared policy (128 KiB request / 1 MiB response) and capability
(8 KiB / 128 KiB) limits additionally cap the configured message limits. Header
blocks are capped at 16 KiB; compression other than identity is disabled.
Protobuf validation bounds nesting, rejects duplicate singular/oneof members,
accepts compatible unknown fields and retains unknown numeric enums. A unary call cannot
silently accept multiple replies. Policy pages require 1..32 and a cursor up
to 117 bytes; capability absent/zero pages keep the default 128 and 160-byte
cursor bound. Lower server limits remain authoritative; there is no auto-paging.

One channel is created per client and connects lazily. Callers share that
thread-safe client rather than constructing one per invocation. It owns one
NIO event-loop thread with finite main/tail task queues (`32 * maximumCalls +
128` entries each), two completion workers and at most `maximumCalls` queued
completions. gRPC retry and hedging are disabled. Internal pending calls,
deadline tasks and encoded/decoded owners are bounded by admitted calls;
connection timers belong to the reusable channel. No unbounded application
executor or thread/channel-per-call is installed.

A channel is not one immutable TCP socket: gRPC can reconnect after a failed
connection or GOAWAY to serve a later explicit call. It does not replay Invoke
or ApplyPolicy on REFUSED_STREAM, GOAWAY or Unavailable. Controlled TCP tests
count each operation exactly once, then execute a fresh explicit status call
and observe socket retirement. RPC deadlines bound calls, not the lifetime of
an otherwise retained channel; use shutdown/close to retire the client and its
remaining transport owners rather than assuming the last RPC closed its socket.

## Deadlines, cancellation and ownership

`CallOptions.timeoutMillis` starts one monotonic deadline at method entry,
before validation, snapshot, connection and RPC. Absent uses the finite configured
default; zero expires without dispatch. Any explicit unsigned relative timeout
above the configured RPC cap fails locally with `Limit`, including high-bit u64
values; it is not misclassified as a negative duration or silently reduced.
The invocation's absolute Unix deadline is compared as unsigned u64 and can only
shorten the finite local budget. Future high-bit deadlines, including u64 maximum,
keep their original exact protobuf bits; only the local remaining time is capped.
Only bounded local milliseconds are converted to nanoseconds. There is no
deadline restart after connect or response conversion. The maintained provider fixture's execution
ceiling also caps `grpc-timeout` at 5000 milliseconds: examples use 3000, and the
held-deadline case uses 500. Do not raise that fixture ceiling or silently retry
with a different timeout when the server rejects an incompatible configuration.

Requests are snapshotted synchronously before the method returns. ByteBuffer's
current remaining slice is copied without changing its position; nested maps,
lists and records are converted to immutable generated messages. Do not mutate
inputs concurrently with that snapshot. Mutation after return cannot change the
wire request. Replies own read-only buffers and immutable collections; they do
not borrow the channel and remain valid after shutdown.

Cancel the returned `CompletableFuture` to cancel the local RPC wait. The legacy
returned future propagates that cancellation too. Cancellation of an unrelated
dependent stage follows standard Java semantics and is not an implicit Cancel
RPC. `Management.ClientCancellationException` carries the same rich failure
facts as other exceptions. Inspect with `Management.clientFailure(throwable)`,
including through bounded `ExecutionException`/`CompletionException` wrapping.
Local cancellation, deadline or closing the client never proves server cleanup
or rolls back a mutation. Use explicit Cancel and GetActivation by the original
caller-known ID; Cancel acceptance is advisory.

Synchronous future continuations must be short and nonblocking. Supply your own
bounded executor for blocking application work. Completion owners remain counted
until continuations return, preventing an unbounded replacement queue. Java
cannot forcibly terminate arbitrary user callbacks: `shutdown(Duration)` returns
a `ShutdownReport` with channel/event-loop/executor termination, active calls and
live owned threads. It reports incomplete cleanup rather than inventing success
when a callback blocks. `close()` uses the configured finite budget and throws
on incomplete cleanup. A later shutdown can observe eventual retirement.
Calling shutdown from an owned callback does not wait on itself.

## Identity, recovery and failures

All bits of Java `long`/`int` represent unsigned protobuf u64/u32 values.
Use `Management.parseU64Decimal` / `formatU64Decimal` for canonical decimal u64,
and unsigned comparisons where required. Do not treat a negative Java long as
a negative wire value. Response timestamps remain raw unsigned data rather than
being coerced into a Java clock. Unknown numeric management enums remain numeric;
unsupported invocation/platform strings fail Decode with bounded raw
`UnsupportedWireValue`, never a fabricated known disposition or retry decision.
The legacy closed cancellation enum rejects future values with the raw evidence.

Typed success, declared application error and platform failure remain distinct
response variants with publication/component and consumption receipts. Failures
retain dispatch/outcome knowledge, raw available gRPC code, bounded typed platform
details, activation/operation identity, and independent audit facts. Transport
messages do not echo server descriptions or credentials. Observed valid receipt
outcome stays distinct from audit failure. An absent operation receipt or
NotFound from GetActivation/GetPolicyOperation is Unknown, not proof of
nonexecution; both exceptional lookups preserve the original recovery ID.

ApplyPolicy requires explicit `expectedGeneration`, including zero for create,
and the caller's nonempty operation ID. Authentication/authorization and document
validation remain node-owned. No client identity generation, authorization,
Invoke retry or mutation resubmission is performed. Recovery looks up the
original operation ID; replay is an explicit caller action with the original
content and precondition.

`auditStatus` and unsigned `auditAttemptSequence` are independent optional raw
facts on both metadata and failures. Known audit text additionally maps to
`AuditAck`; bounded unknown visible-ASCII text (including digits) retains its raw
sequence without inventing any enum. Missing audit stays absent. In particular,
current real-node ApplyPolicy emits no acknowledgement: the participant requires
all three fields absent and returns `auditAttempt: null`. Controlled peers test
known/future audit status and `18446744073709551615` separately.

## Native provider example and qualification

After authenticated operator setup has admitted the maintained HTTP and blob
guests, copy their exact service/route/contract/function/publication/component
identities into [the configuration template](examples/provider-config.example.json).
Keep the client credential in a private file, never argv or a public deployment
default. The example checks POSIX secret-file permissions; Windows users must
protect the file with an appropriate private ACL. The example receives only a
node credential, never HTTP/blob provider credentials or capability authority.

```sh
java -cp sdk/java-client/build/latent-java-client.jar dev.latent.sdk.examples.ProviderExample \
  --config /private/java-provider.json --activation-prefix java-example-01
```

Use a fresh explicit caller-known prefix for a new run. The program invokes the
authorized guests with the supported WIT-value media type. HTTP/blob arguments
are `[0, URL, "0"]` / `[0, "", "0"]`; u64 handles/results stay decimal strings
inside that application framing. Payload bytes otherwise remain opaque to the
transport. The example does not make provider HTTP/blob requests itself.

`dev.latent.sdk.examples.ProviderWorkflow` is the native participant for the
[shared separate-node workflow](https://github.com/KirilsTurkins/latent-service-fabric/blob/feat/sdk-real-node-qualification/docs/testing/sdk-provider-workflow.md):

```sh
python3 tools/run_sdk_provider_workflow.py \
  --cli /absolute/latent --node /absolute/latentd \
  --fixture-root /absolute/signed-fixture --language java \
  -- /absolute/java -jar /absolute/sdk/java-client/build/latent-java-client.jar
```

The JAR's main class is `ProviderWorkflow`. Passing its absolute path lets the
runner retain both the Java executable and SDK JAR hashes. The runner appends
`--config`. The participant executes all eighteen required
checks and returns nine admitted activation IDs, one exact operation ID, and
no private payloads. Four atomic rendezvous modes exercise local cancellation,
explicit Cancel/status, the original deadline and shutdown independently. It
requires actual provider started/closed markers and retained terminal status;
it cannot substitute a sleep or local future state for physical cleanup. Its
application-owned logging configuration suppresses dependency JUL chatter so
the runner gets one bounded JSON result and no stderr on success. Failures use
fixed redacted stage/category diagnostics. It does not alter server audit policy
or provider grants.

See [validation evidence](EVIDENCE.md). Controlled TCP tests are not real-node
qualification; parent-owned exact-head CI and acceptance review remain required.
