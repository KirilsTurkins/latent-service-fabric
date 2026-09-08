# Standalone node

`latentd serve` runs the Phase 1 stateless node on Linux. One process composes
durable release and deployment catalogs, immutable routing, admission and quotas,
fixed execution cells, generic Wasmtime execution, activation capabilities,
bounded lifecycle/status retention, telemetry, and the invocation and management
RPC adapters. Worker and listener counts come from node configuration and do not
grow with deployed services.

The [`latent` operator CLI](operator-cli.md) uses the generated clients to publish,
deploy, invoke, cancel, and inspect; the
[scriptable echo quickstart](../development/standalone-quickstart.md) starts a node
with an ephemeral endpoint and private credentials. Generated Tonic clients can
also use the [management](management-services.md) and
[invocation](../protocol/invocation-service.md) contracts directly. The Phase 0
`phase0-spike`/`spike` command family keeps its existing arguments, payload
convention, output and exit codes.

## Start a local node

Install the [pinned build prerequisites](../development/toolchain.md), then build
the executable:

```bash
cargo build -p latentd --locked
```

Create `node.json`, replacing the token placeholder with a private random token
before starting. For example, `python3 -c 'import secrets; print(secrets.token_urlsafe(32))'`
produces a token accepted by this configuration format.

```json
{
  "formatVersion": 1,
  "dataDirectory": "data",
  "bind": "127.0.0.1:50051",
  "nodeId": "local-node",
  "credentials": [
    {
      "token": "REPLACE_WITH_A_GENERATED_BASE64URL_TOKEN",
      "subject": "local-operator",
      "tenant": "examples",
      "role": "operator"
    }
  ]
}
```

```bash
./target/debug/latentd serve --config ./node.json
```

The configuration contains literal values; it does not expand shell variables.
Keep its credentials private. Send exactly one HTTP/2 metadata header
`authorization: Bearer <token>` on each RPC. Missing, repeated, or unknown
credentials fail authentication. The listener uses plaintext gRPC on a literal
loopback IP address; non-loopback binds are rejected. Port `0` is supported and
the startup record reports the actual bound endpoint.

`serve` rejects non-Linux hosts before opening configuration or storage. Linux
must provide usable local filesystem locking and directory synchronization for
the durable catalogs, and readable CPU/memory pressure observations for activation
readiness. A running listener with unavailable pressure can still serve authorized
management requests, while activation admission fails closed.

## Configuration contract

`formatVersion`, `dataDirectory`, `nodeId`, and a nonempty `credentials` array are
required. Other fields have the defaults below; nested optional fields can be
omitted independently. Unknown fields, duplicate fields, unsupported versions,
and invalid combinations fail before runtimes, catalog ownership or listeners
are created. The reader accepts at most 64 KiB and checks depth and structural
counts before deserializing containers.

Rust embedders configure `NodeConfig`, then call `derive()` to obtain an opaque
`NodeSettings` plan for `StandaloneNode::start`. Derived fields cannot be changed
or constructed externally after validation. Read-only `runtime_workers()`,
`control_workers()` and `shutdown_grace()` accessors provide the values needed to
own the outer runtimes; configuration changes require deriving a new plan.

Relative `dataDirectory` paths are anchored once to the configuration file's
existing canonical parent. The data directory is created during startup, with
separate `releases/` and `deployments/` roots. Paths and credentials are omitted
from startup failure diagnostics.

| Field | Default | Meaning and supported bounds |
| --- | --- | --- |
| `bind` | `127.0.0.1:50051` | Loopback IP literal; port zero selects an ephemeral port. |
| `workers.runtime` | `2` | Fixed invocation/network runtime workers, 1–32. |
| `workers.control` | `2` | Fixed control runtime workers and maximum concurrent management jobs, 1–8. |
| `cells` | One `standard` class, capacity 2, queue capacity 16, memory 64 MiB | Up to five known classes; details below. |
| `execution.maximumCpuFuel` | `100000000` | Per-activation node fuel ceiling, 1–10 billion. |
| `execution.maximumWallTimeMillis` | `1000` | Activation wall-time and transport request ceiling, 2–300000 ms. |
| `execution.maximumLogBytes` | `16384` | Per-activation log allowance, 0–16384 bytes; zero denies logs. |
| `limits.maximumComponentBytes` | `16777216` | Upload, repository and backend component ceiling, up to 64 MiB. |
| `limits.maximumPayloadBytes` | `1048576` | Invocation/codec input and output ceiling, up to 1 MiB. |
| `limits.maximumConnections` | `32` | Accepted transport connections, 1–1024. |
| `cache.entries` | `8` | Retained prepared components, 1–4096. |
| `cache.sourceBytes` | `67108864` | Retained source ceiling, at least one maximum component and at most 1 GiB. |
| `cache.metadataBytes` | `8388608` | Retained preparation metadata, 1 MiB–1 GiB. |
| `cache.compiledImageBytes` | `134217728` | Retained compiled image ranges, at most 1 GiB. |
| `cache.preparations` | `1` | Concurrent preparations, no greater than fixed cells or control workers. |
| `catalogs.releaseEntries` | `4096` | Completed-release index count, at most 100000. |
| `catalogs.releaseIndexBytes` | `67108864` | Release index allocation ceiling, 1 MiB–1 GiB. |
| `catalogs.deployments` | `4096` | Deployment count, at most 100000. |
| `catalogs.deploymentStateBytes` | `67108864` | Deployment/compiler state ceiling, 1 MiB–1 GiB. |
| `retention.terminalEntries` | `1024` | Retained terminal activation count, at most 100000. |
| `retention.terminalTtlMillis` | `300000` | Monotonic terminal retention, 1–86400000 ms. |
| `retention.bytes` | `268435456` | Journal allocation ceiling, at most 1 GiB; all active reservations must fit. |
| `telemetry.queueEntries` | `128` | Shared exporter queue, 1–4096 records. |
| `telemetry.retainedEntries` | `1024` | Local diagnostic capture, 1–65536 records. |
| `telemetry.retainedBytes` | `8388608` | Local diagnostic allocation ceiling, 64 KiB–256 MiB. |
| `shutdownGraceMillis` | `1000` | Bounded drain/transport/runtime shutdown interval, 1–60000 ms. |

A cell entry has `class`, `capacity`, `queueCapacity`, and `maximumMemoryBytes`.
Known classes are `tiny`, `small`, `standard`, `large`, and `extra-large`. Omit
disabled classes. Every configured capacity and queue is positive; larger classes
cannot have smaller memory ceilings. Total cells are at most 64, and total cells
plus queue capacity are at most 1024. Memory is 64 KiB–1 GiB per class.

The fixed trust class is `internal`, matching the existing deployment examples.
The runtime supports stateless single-threaded and reentrant components. Host
architecture and operating system are measured by the executable; configuration
does not invent CPU feature support or expose arbitrary capability/claim policy.

Let `C` be total cell capacity and `Q` total queue capacity. Admission and journal
active ceilings use `R = C + Q`, because admission reserves CPU and memory for
queued work as well as running work. A journal activation reserves 4 MiB, so
`R × 4 MiB` must fit `retention.bytes`. Terminal records are evicted by count,
bytes or age; configured entry counts do not guarantee that maximum-size entries
all fit simultaneously.

## Authentication and execution boundary

There are 1–64 configured credentials. Tokens are unique, 32–256 ASCII characters
from letters, digits, `_` and `-`. Subjects are bounded identifiers. Tenant names
follow the manifest namespace grammar: 1–128 ASCII characters, alphanumeric ends,
with internal `-`, `_` or `.` permitted.

| Role | Trusted principal and access |
| --- | --- |
| `invoke` | User principal for invocation, cancellation and retained status in its configured tenant. |
| `admin` | Administrator principal for that tenant's invocation and supported release/deployment/route operations. |
| `operator` | Administrator with the fixed `latent.node.operator=true` claim, additionally permitting node inventory. |

Every role remains exactly tenant scoped. An administrator cannot submit a
foreign tenant or use caller metadata to acquire another identity. Root/parent
activation identifiers remain validated correlation claims; they grant no
authority. Context exposure retains only the `guest.` metadata prefix by default;
claim and baggage allowlists are empty. Guest log bodies and unknown fields are
redacted before telemetry submission.

The configured node shares one quota ledger, scheduler, manager, clock and
Wasmtime preparation cache. Each activation receives a fresh store and owned
cleanup obligations. The cache holds prepared code and bounded metadata; cache
bytes do not measure process RSS, compiler scratch memory, or evicted code pinned
by an active invocation. Publication validates durable artifacts; it does not
promise that every published component's imports, types, metadata or declared
resources fit this particular runtime.

The listener serves Invoke/Cancel/GetActivation and the supported release,
deployment, route and node RPCs. Documented future methods return `Unimplemented`.
There is no cluster controller, remote identity handshake, TLS configuration,
service-specific listener, or persistent guest instance in this composition.

## Transport, readiness and pressure

Accepted connections and RPCs have separate fixed bounds. Global RPC capacity is
`R + workers.control + 4`, with four slots reserved for Cancel/GetActivation.
Management work obtains a control-job permit before spawning its entire adapter
future on the control runtime. Full gates reject promptly; there is no additional
unbounded management queue. RPC ownership spans request-body decoding through
response-body completion or drop. Dropping a network waiter does not release a
started operation's guard before its actual future is destroyed.

HTTP/2 headers are bounded to 16 KiB and concurrent streams to 32 per connection,
with fixed frame/flow-control bounds. Each runtime allows at most one additional
blocking thread. Invocation deadlines are anchored at transport arrival, so time
spent waiting for the request body does not restart the deadline at manager entry.

One control-runtime sampler reads `/proc/pressure/cpu` and
`/proc/pressure/memory` every 250 ms. It uses `some.avg10`: the kernel's ten-second
trend for time during which at least some tasks stalled on that resource. The
percentage is converted to a 0–1000 value, rounding down to whole milli units.
These are system pressure observations, distinct from CPU utilization or resident
memory size. See the [Linux PSI documentation](https://docs.kernel.org/accounting/psi.html).

Missing, malformed or stale observations do not become fresh zero pressure.
Admission and inventory require samples no older than two seconds. CPU or memory
pressure at or above 950 marks the node unready and rejects new activations.
Shutdown also closes admission. Busy cells can remain ready while accepting a
bounded queue; unavailable usable cells and closed scheduler gates make readiness
false. Inventory exposes unavailable observations explicitly and reports fixed
topology counts separately from measured live counts.

Startup writes one flushed JSON line using schema
`latent.standalone.status.v1`. Its event is `ready` when the initial inventory
reports ready, otherwise `started` with `ready:false`. It includes the configured
node ID and actual endpoint. Query authorized node inventory for subsequent
readiness; a bound listener alone is not evidence of activation readiness.

## Durable restart and shutdown evidence

Startup owns and verifies the release root, then opens the deployment root and
rebuilds the compiled catalog before enabling RPC acceptance. Corrupt committed
metadata, incompatible catalog formats, ownership conflicts and recovery errors
fail startup. Restart with the same data directory preserves release/deployment
identities and route generation. Activation history, telemetry capture and
prepared code are bounded in-memory state and are rebuilt or empty after restart.
Follow the catalog-specific [recovery guidance](../development/local-release-catalog.md);
do not repair integrity failures by replacing completion records or deleting
committed state blindly.

Ctrl-C or SIGTERM closes acceptance, allows the configured activation drain
interval, then cancels outstanding owners and shuts down transport and sampling.
The node checks actual transport/control ownership, journal/cancellation state,
quota reservations, queued work, cell leases, backend instance reservations,
pending preparations and their source/metadata charges, and live stores,
instances and host state before flushing telemetry and joining the epoch helper.
Quarantined cells remain visible in the report. The command then shuts down both runtime owners and
requires their observed thread counts to reach zero.

A clean exit emits a final bounded, flushed `stopped` JSON record with the
`ShutdownReport`. No clean record is emitted when cleanup fails or its watchdog
expires. Diagnostics use fixed stage and platform-code strings; invalid command
or configuration exits with code 2, and other failures with code 1. Unexpected
server termination also triggers cleanup and an unsuccessful exit.

The outer watchdog includes drain, transport, sampler, activation cleanup,
telemetry and coordination allowances. Runtime shutdown uses bounded waits.
These bounds cannot kill a thread already inside a stuck filesystem call or
other non-cooperative operating-system work. Such a timeout is failure evidence,
not proof that the work stopped. A clean finite run establishes the reported
cleanup for that run; it does not establish long-running reclamation, dormant
100000-service scale, or completion of the Phase 1 gate (#16).

See [validation commands](../../VALIDATION.md) for the focused configuration,
transport, catalog and execution tests. No heavy scale or soak run is required
to exercise these startup and shutdown checks.
