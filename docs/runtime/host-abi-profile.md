# Host ABI compatibility profiles

Use the engine pinned in [the toolchain baseline](../development/toolchain.md#selected-versions)
and the committed Cargo lock. The [security upgrade record](../development/wasmtime-security-update.md)
separates that current selection from dated qualification and native-artifact
identities; an older receipt does not qualify a different engine.

`lsf-host-abi-phase3-v5` is the current generic recognition profile in
`latent-core`. The [frozen matrix](../../wit/host-abi-phase3-v5.json) records its
exact interface identities, source hashes, function forms and installed bindings.
[ADR-0031](../../adr/0031-version-host-abi-recognition-independently-of-provider-authority.md)
and [RFC-0005](../../rfcs/0005-phase3-host-abi-profiles.md) define its ownership,
error and compatibility contract; [ADR-0032](../../adr/0032-use-bounded-owned-resources-for-streaming-http.md) adds the exact streaming resource extension. [ADR-0033](../../adr/0033-use-scoped-durable-local-blobs-with-owned-chunks.md) adds immutable blobs with owned chunks.

## Recognition and availability

| Exact interface | Inspection | Production binding |
| --- | --- | --- |
| `latent:context/context@0.1.0` | supported | built in |
| `latent:log/log@0.1.0` | supported | built in |
| `latent:clock/monotonic@0.1.0` | supported | built in |
| `latent:clock/wall@0.1.0` | supported | built in |
| `latent:random/random@0.1.0` | supported, synchronous WIT with cooperative audit waits | configured [OS randomness provider](random.md) |
| `latent:blob/blob@0.1.0` | supported, legacy | unavailable |
| `latent:blob/blob@0.2.0` | supported, async owned chunks | configured Linux [local](local-blobs.md) or [S3](s3-blobs.md) blob adapter |
| `latent:secrets/reader@0.1.0` | supported, synchronous WIT with cooperative host waits | configured [local](local-secrets.md) or [Vault KV-v2](vault-secrets.md) secret provider |
| `latent:events/publisher@0.2.0` | supported, synchronous WIT with cooperative host waits | configured [NATS JetStream publisher](nats-events.md) |
| `latent:http/streaming@0.3.0` | supported, async owned resources | configured [streaming HTTP adapter](streaming-http.md) |
| `latent:http/client@0.2.0` | supported, async import | configured [bounded HTTP adapter](outbound-http.md) |
| `latent:telemetry/custom@0.1.0` | supported, synchronous WIT with cooperative audit waits | configured [shared custom metrics](custom-metrics.md) |
| `latent:service/invoke@0.1.0` | supported, async import | configured [isolated local adapter](local-service-invocation.md) |
| `latent:runtime/activation@0.1.0` | supported, activation ownership and waits | opt-in engine configuration and exact independent grant; language ports need separate qualification |
| `latent:network/streams@0.1.0` | supported, exact owned connection/chunk resources | unavailable by default; [development TCP provider](../reference/standalone-streams.md) requires its explicit build feature and separate qualification |

"Built in" identifies a host implementation, not an installed standalone grant.
The node's [provider configuration](../reference/standalone-providers.md) must
still install and bind the exact context, log or clock provider required by the
selected capsule. Generic recognition cannot supply a missing owner, and an
unlisted composition remains untested by the developer support matrix.

An inspected package has no provider authority. Wasmtime preparation rejects a
required provider that has no installed owner. The generated host/guest
bindings contain types and registration helpers; the production linker supplies
context, log and clock, plus service invocation, buffered/streaming HTTP, local/S3 blobs, local/Vault secrets, NATS publication, cryptographic randomness and custom metrics when their node-owned
adapters are installed. Activations must supply their exact prepared
imports and pass current eligibility/descriptor checks.

The complete source interface must match authoritative WIT. A compiler may prune
unused binary imports/members; every retained member still needs its exact
version and complete supported shape. A matching name, partial supplied WIT or
forged metadata cannot authorize a different host ABI. Parser, graph, comparison
and transfer limits remain independent checks. Complete host comparison shares
one finite work allowance across all required interfaces.

## Selected forms and versions

The v1 four-interface profile remains defined. Existing context/log/clock bytes
and versions are unchanged. The legacy aggregate world at 0.1.0 and its Rust
bindings remain available; the aggregate at 0.2.0 selects v2. The separate
0.3.0 aggregate selects V3 and includes both HTTP package versions. The 0.4.0
aggregate selects V4 and additionally includes both blob versions. The 0.5.0
aggregate selects V5 and adds activation ownership/waits and scoped outbound
streams. V1/V2/V3/V4
sources and identities remain unchanged. Binding staging
loads only the referenced package versions to preserve generated module names.

HTTP and events use explicit 0.2.0 package versions because their errors and
receipts changed. HTTP reports a complete response or a typed failure, including
uncertainty after possible dispatch. Events report broker stream/sequence and
acknowledgement, including duplicate status, or an explicit uncertain outcome.
Neither implies a transaction, consumer processing or automatic retry authority.

HTTP/service/blob operations select freestanding async imports. Local secret reads use their existing synchronous WIT with a cooperative async
host bridge. Neither form makes
waiting activations free: stores, cells, handles, buffers and reservations stay
owned until completion or affirmative cleanup.

The local service, buffered/streaming HTTP and local blob profiles additionally
select freestanding async application
exports so callers can wait for the canonical async import. Exact source, binary
and contract metadata must agree, and production preparation requires an installed async
adapter. The frozen host WIT and digest remain unchanged. V3 additionally accepts exact upload/body/chunk own/borrow resources only in
`latent:http/streaming@0.3.0`. V4 additionally accepts exact chunk own/borrow
positions in `latent:blob/blob@0.2.0`. V5 accepts exact connection/chunk
positions in `latent:network/streams@0.1.0`. Application exports still use the bounded value
codec. Other resource identities, implicit futures/streams, maps, fixed lists
and error-context remain rejected. [Blob tokens](local-blobs.md) retain their separate lifecycle;
state uses the separately selected Phase 4 transaction profile described below. Runtime waits require their own exact
capability and preserve the original activation deadline. Clock-read permission
does not authorize a wait or any timer. See the [streaming ownership and
limits](streaming-http.md).


## Explicit transaction profile

`lsf-host-abi-phase4-v1` has its own
[frozen matrix](../../wit/host-abi-phase4-v1.json) and
[transaction preparation contract](../protocol/transactions.md). It selects
`latent:state/key-value@0.2.0` and `latent:intents/staging@0.1.0` for host-created
commands and independent fresh queries. It does not broaden ordinary V5
capability grants or authorize immediate application effects inside a strict
command. Installing its compiler inputs does not install namespace authority,
protected storage or dispatch providers.

Use [the installed runtime](../development/installed-transaction-rpc.md) for node
composition and [transactional authoring](../component-development/transactional-authoring.md)
for guest inputs. A recognized import, signed component or successful preparation
is separate from signed-node, client/application and packaged qualification.

## Cache identity and security

The canonical SHA-256 profile identity covers the ID, ordered exact interface
names, package names, binding kind, async flag and complete WIT bytes. Lengths
are framed as little-endian u64 values with a versioned domain separator. The
profile ID and digest enter generic preparation compatibility; AOT uses the same
capability digest alongside engine/input/policy identities. Old generic prepared
or native artifacts require regeneration. Source comments conservatively affect
identity; repository LF line endings are checked.

Mutable grants and credential rotations do not authorize native code through a
cache key. Eligibility, exact descriptors and required activation bindings remain
checked at invocation. The [sealed broker](capability-broker.md) and
[exact binding compiler](capability-bindings.md) implement live policy, provider
epoch and publication checks independently of ABI recognition.

The toolchain baseline pins the engine and guest generator independently. No WASI
filesystem, HTTP or WASIp3 streams are installed. Expanding that surface requires
an advisory reachability review. ABI compatibility does not establish a stronger
[execution isolation profile](../../rfcs/0001-minimum-execution-isolation-profiles.md).
External-capsule deployments require their selected
[execution security profile](execution-security-profiles.md). Separate-process
guest execution hosts remain unavailable; ABI recognition does not provide one.

Normal CI parses the maintained worlds, compiles native/Wasm generated bindings and tests
real component/linker compatibility, wrong shapes/versions, missing providers,
forged/stale descriptors, comparison limits and schema/source/generator parity.
The fixtures allocate no dormant application resources and provide no provider
performance or hostile-multitenant qualification claim.
