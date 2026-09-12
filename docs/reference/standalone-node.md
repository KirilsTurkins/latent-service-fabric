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
  "supplyChain": {"mode": "trusted-local"},
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

The [authenticated package admission](package-admission.md) mode is selected
with `"supplyChain":{"mode":"enforced","policyFile":"admission-policy.json",
"clockLeaseSeconds":5}`. The policy path is also anchored to the configuration
directory. It requires a complete bounded publisher/builder/revocation/SBOM and
tenant-authorization policy. An omitted member or explicit `trusted-local` keeps
Phase 1 compatibility only for local catalogs; an existing enforced root refuses
that downgrade. The [member schema](../../schemas/node-supply-chain.schema.json)
describes both closed forms. Changing the policy file does not automatically
reload live trust; the host replacement API owns that transaction.

| Field | Default | Meaning and supported bounds |
| --- | --- | --- |
| `bind` | `127.0.0.1:50051` | Loopback IP literal; port zero selects an ephemeral port. |
| `workers.runtime` | `2` | Fixed invocation/network runtime workers, 1–32. |
| `workers.control` | `2` | Fixed control runtime workers and maximum concurrent management jobs, 1–8. |
| `cells` | One `standard` class, capacity 2, queue capacity 16, memory 64 MiB | Up to five known classes; details below. |
| `execution.maximumCpuFuel` | `100000000` | Per-activation node fuel ceiling, 1–10 billion. |
| `execution.maximumWallTimeMillis` | `1000` | Activation wall-time and transport request ceiling, 2–300000 ms. |
| `execution.maximumLogBytes` | `16384` | Per-activation log allowance, 0–16384 bytes; zero denies logs. |
| `engine.allocator` | `"on-demand"` | `"on-demand"` or `"pooling"`. Pooling derives its component and stack slots from the checked total execution-cell capacity. |
| `engine.optimization` | `"speed"` | Cranelift `"speed"` or `"speed-and-size"`; both retain fuel, epoch interruption and async execution. |
| `limits.maximumComponentBytes` | `16777216` | Upload, repository and backend component ceiling, up to 64 MiB. |
| `limits.maximumPayloadBytes` | `1048576` | Invocation/codec input and output ceiling, up to 1 MiB. |
| `limits.maximumConnections` | `32` | Accepted transport connections, 1–1024. |
| `cache.entries` | `8` | Retained prepared components, 1–4096. |
| `cache.sourceBytes` | `67108864` | Associated component-byte ceiling for resident code, at least one maximum component and at most 1 GiB; not retained source buffers. |
| `cache.metadataBytes` | `8388608` | Resident preparation metadata accounting ceiling, 1 MiB–1 GiB. |
| `cache.compiledImageBytes` | `134217728` | Retained compiled image ranges, at most 1 GiB. |
| `cache.preparations` | `1` | Total distinct compiler jobs, assigned plus queued; at most the admitted population (cells plus queue capacity). |
| `cache.compilerWorkers` | `min(2, cache.preparations)` | Fixed compiler threads, 1 to 8 and no greater than total compiler jobs. Remaining job slots form the bounded compiler queue. |
| `catalogs.releaseEntries` | `4096` | Completed-release index count, at most 100000. |
| `catalogs.releaseIndexBytes` | `67108864` | Release index allocation ceiling, 1 MiB–1 GiB. |
| `catalogs.deployments` | `4096` | Deployment count, at most 100000. |
| `catalogs.deploymentStateBytes` | `67108864` | Deployment/compiler state ceiling, 1 MiB–1 GiB. |
| `supplyChain` | `{"mode":"trusted-local"}` | Explicit local compatibility or `enforced` with a required policy file. |
| `supplyChain.clockLeaseSeconds` | `5` in enforced mode | Durable future clock lease, integer 1–5 seconds; restart before its persisted floor fails closed. |
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

Compiler jobs use their own fixed workers, independently of invocation and
management workers. Same-key waiters and ready pins are each bounded by the
admitted population. Queued and assigned jobs retain source/metadata reservations;
encoded document reservations are separately bounded by the number of jobs times
the repository and manifest document ceilings plus fixed read allowance. These
input and ownership charges do not measure transient decoder or compiler heap.

One fixed async cleanup driver runs on the invocation runtime. Its continuation
slots equal total cells plus queue capacity, with the same 1024-slot ceiling,
and are reserved before activation acceptance. A disconnected or timed-out RPC
hands over its existing activation owner; no invocation is restarted and no
deadline is renewed. Standalone's backend cleanup grace is fixed at 100 ms,
giving each handoff a 200 ms absolute cap that includes scheduling and pool
disposition. These are derived limits, not additional JSON settings. Missing
cleanup proof preserves cell quarantine; a cap overrun is reported as failure.

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

## Optional isolated AOT compilation

On Linux x86_64, `isolatedAot` selects the bounded isolated compiler and persistent
authenticated native cache described in [trusted AOT](../runtime/trusted-aot.md).
Omitting this member keeps ordinary portable compilation. A configured node
fails if its compiler approval, private key, storage, or sandbox prerequisites
cannot be established. A cache miss or rejected cached image can trigger one
isolated compilation of the current catalog-owned source; it never selects an
in-process compiler fallback. Both trusted-local and enforced catalogs retain
their independent lifecycle and admission checks.

Add this member to the node document. Replace the compiler digest placeholder
with the exact SHA-256 of your approved `latent-aot-compiler` executable; the
example is not executable configuration until that placeholder is replaced.

```json
{
  "isolatedAot": {
    "compilerExecutable": "/opt/lsf/bin/latent-aot-compiler",
    "compilerDigest": "sha256:REPLACE_WITH_64_LOWERCASE_HEX_DIGITS",
    "keyFile": "/etc/lsf/private/native-aot.key",
    "blobRoot": "/var/cache/lsf/native-blobs",
    "receiptRoot": "/var/cache/lsf/native-receipts",
    "process": {
      "jobTimeoutMillis": 30000,
      "maximumOutputBytes": 134217728,
      "addressSpaceBytes": 536870912
    },
    "cache": {"entries": 1024, "diskBytes": 268435456},
    "images": {
      "maximumImages": 64,
      "maximumImageBytes": 134217728,
      "maximumTotalBytes": 268435456
    }
  }
}
```

The five path/identity members are required. The three limit groups may be omitted
or partially specified; shown values are defaults. The
[member schema](../../schemas/node-isolated-aot.schema.json) is closed: unknown
members, literal key bytes and explicit null are rejected. The runtime decoder
also rejects duplicate members.
The compiler path is absolute and never searches `PATH`. Relative key and cache
paths are anchored to the config directory. Key and cache paths are bounded to
4096 UTF-8 bytes and 256 components, with no parent-directory segments. Existing
ancestors are resolved before comparing roots; future cache directories are
created only during startup. The two cache roots cannot overlap each other or
the node data directory.

Provision a cryptographically random, nonzero **32-byte binary key** separately
under a private directory owned by the node service UID. The file must be a
regular file owned by that UID, with one hard link and mode `0600` or `0400`;
the parent has no group/other permission bits. Symlink key files are rejected.
The key must be outside the entire data directory and both cache roots. For an
existing private directory, this bounded provisioning example creates a new file
exclusively and refuses to replace an existing key:

```bash
python3 -c 'import os,secrets; fd=os.open("/etc/lsf/private/native-aot.key",os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600); stream=os.fdopen(fd,"wb"); stream.write(secrets.token_bytes(32)); stream.close()'
sha256sum /opt/lsf/bin/latent-aot-compiler
```

Run provisioning as the service UID; prepare the parent directory with private
permissions first. The configuration reader loads and validates the key once
before opening catalogs or workers. It neither creates nor regenerates keys.
Changing or losing this host key makes earlier native receipts unusable; cache
contents do not supply replacement authority. Keys and paths are absent from
error diagnostics. Trusted host administrators and the service UID remain
outside the cache-tampering threat boundary.

| AOT field | Supported bounds and accounting |
| --- | --- |
| `process.jobTimeoutMillis` | 1–300000 ms, including time after reserving a queued job; independent of a caller's deadline. |
| `process.maximumOutputBytes` | Positive and at most 256 MiB per serialized native result. |
| `process.addressSpaceBytes` | 64 MiB–4 GiB per compiler child; includes executable mappings and trusted setup. |
| `cache.entries` | 1–16384 native/receipt entries. Byte and metadata bounds may fill first. |
| `cache.diskBytes` | At most 4 GiB of native payload bytes, with room for one maximum result. Default 256 MiB. Small per-entry ownership headers are separately bounded. |
| `images.maximumImages` | 1–4096 live native mappings, including prepared/ready/active pins after resident eviction. |
| `images.maximumImageBytes` | At most 256 MiB per page-rounded mapping; must fit a maximum output rounded to the host page size. |
| `images.maximumTotalBytes` | At most 1 GiB of simultaneously owned native mappings, and at least the per-image limit. |

Producer job/output slots are `min(cache.preparations, 8)` and use the existing
fixed compiler workers. Input, document and output byte allowances are derived
with checked multiplication; impossible combinations reject instead of raising
hard limits. Input totals cap at 512 MiB, document totals at 512 MiB, and produced
native totals at 1 GiB. Document accounting includes bounded encoded inputs,
metadata acceptance and fixed validation scratch; it does not measure transient
decoder heap. Child CPU seconds are the rounded-up job timeout; child stack is
8 MiB and its descriptor limit is 16.

The native cache additionally bounds staging and retained read buffers separately
to `max(128 MiB, maximumOutputBytes)`, with two staging slots, eight read owners,
64 pins, four filesystem work owners and 2 MiB of index metadata. The receipt
cache has a separate 16 MiB disk cap, 2 MiB metadata cap, one fixed stage, an 8 KiB
per-receipt cap and eight retained reads sharing 64 KiB. Raw-cache recovery visits
at most twice the configured entry count. Receipt recovery uses the larger of
twice the entry count or the entry count plus three, including its marker, lock
and stage. These are maximum populations,
not a promise that every slot fits a maximum-size entry simultaneously. Default
native plus receipt disk ceilings are 272 MiB, excluding bounded raw-entry headers,
small registered root metadata and filesystem allocation overhead.

Native file bytes, retained read buffers, compiler output and live mapped images
are separate ownership domains. Their limits do not claim whole-process RSS:
Wasmtime type metadata, linker/unwind allocations and possible lazy COW backing
have distinct costs. Existing `cache.compiledImageBytes` still limits resident
prepared entries; eviction cannot refund a mapping held by a ready or active
owner. Startup, cancellation and shutdown retain producer ownership until an
actual child exit is observed.

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
cleanup obligations. The resident cache uses expected O(1) borrowed-key lookup
and recency promotion, shared `Arc<str>` keys and a reusable arena bounded by
`cache.entries`. Its entry and byte admission gates remain in force.

The optional `engine` object selects allocator and compiler policy. Omitting it
preserves on-demand allocation and speed optimization. Pooling reserves bounded
component, core-instance, memory, table and async-stack capacity from the total
execution-cell count; it never permits additional active invocations. Every
activation still receives a fresh store and instance. Linear memories are reset
on reuse, unused warm pool slots and retained page budgets are zero, and
decommit batches contain one slot. Async-stack zeroing remains disabled; the
guest-memory reset guarantee does not describe cleared native stack bytes.
Pool reservations, compiled image spans and process RSS measure different
resources. Pooling also changes memory reservation and guard policy, so its
performance comparison includes those layout choices. Compiler and resolved
layout/reset settings participate in preparation compatibility identity.

Use the [measured engine profiles](../../benchmarks/optimization/engine-profiles/2026-09-09-container-linux-fbb6e26/README.md)
to assess a configuration change. In the retained four-workload comparison,
pooling/speed reduced warm setup by 16–29 us, with higher compilation cost,
sampled RSS and compiled-image charges. Its lower virtual-memory high-water
usage does not imply lower resident memory. Pooling is an option for repeated
prepared invocations when that tradeoff fits the workload. Speed-and-size did
not reduce compiled-image charges in these fixtures. On-demand/speed remains
the default.

RPC inventory retains its resident-cache counters. The backend and factory Rust
APIs additionally expose `cache_accounting_snapshot()` and an independent
`prepared_runtime_observer()`: unique runtimes are counted once across
`unpublished`, `resident` and `evicted_live`, with `live` reporting their total.
Evicted code can remain owned by ready or active pins, or temporary compiler
owners. Conservative `ReadyGate` charges still apply separately to every ready
owner, including owners sharing one runtime. Source bytes describe associated
component content; metadata bytes are bounded accounting estimates, and compiled
image bytes are address spans. None measures process RSS, physical pages or
compiler scratch memory. The observer retains only counters and can verify final
runtime release after factory destruction. See the
[runtime accounting contract](../runtime/wasmtime.md#node-policy-and-shared-preparation)
for the API and unavailable-value semantics.

Trusted-local publication validates durable artifacts without authenticating
their publisher or builder. Enforced publication additionally checks complete
package semantics and current supply-chain policy. Both still require runtime
resource, capability and deployment checks before execution.

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
interval, then closes compiler admission at that cutoff, cancels outstanding
RPC owners, and shuts down transport and sampling. Existing continuation
reservations can still transfer their exact owners after admission closes.
The cleanup driver drains concurrently with transport cancellation, using one
200 ms forced-cleanup cutoff after natural drain. Transport retains its separate
shutdown allowance; neither extends an activation's execution deadline.
Successful shutdown requires the driver to join before final resource
observations. Startup failures after service creation also run this shutdown path.
The node checks actual transport/control ownership, journal/cancellation state,
quota reservations, queued work, cell leases, backend instance reservations,
pending preparations and their source/metadata charges, ready pins, compiler
queues, waiter registrations, encoded document reservations, and live stores,
instances and host state. Cleanup observations also require zero reserved,
queued and running continuations, a joined driver, and no failed handoffs.
It closes compiler admission and waits for actual worker
quiescence before these observations, then flushes telemetry and joins every
compiler worker and the epoch helper.
Quarantined cells remain visible in the report; a clean ownership report alone
does not prove that all configured cells are reusable. The command then shuts down
both runtime owners and requires their observed thread counts to reach zero.

A clean exit emits a final bounded, flushed `stopped` JSON record with the
`ShutdownReport`. No clean record is emitted when cleanup fails or its watchdog
expires. Diagnostics use fixed stage and platform-code strings; invalid command
or configuration exits with code 2, and other failures with code 1. Unexpected
server termination also triggers cleanup and an unsuccessful exit.

The outer watchdog includes drain, transport, sampler, activation cleanup,
telemetry and coordination allowances. Runtime shutdown uses bounded waits.
These bounds cannot kill a thread already inside a stuck filesystem call or
other non-cooperative operating-system work. Wasmtime's native compilation is
synchronous and cannot be force-cancelled with guest fuel or epoch interruption.
The original drain deadline also bounds native compiler work: the node records
the latest actual job completion and rejects clean shutdown if that work finishes
late, including during transport cleanup. Idle worker wake/exit scheduling does
not count as extra invocation work. Compiler quiescence and final joins retain
the factory and reservations until actual completion, so teardown may outlast
grace even though the run reports failure. An outer process supervisor supplies
the hard termination boundary. A timeout is failure
evidence, not proof that the work stopped. A clean finite run establishes the reported
cleanup for that run; it does not establish long-running reclamation, dormant
100000-service scale. The retained [Phase 1 measurements](../testing/phase-1-measurements.md)
provide that separate evidence for their recorded source revisions.

See [validation commands](../../VALIDATION.md) for the focused configuration,
transport, catalog and execution tests. No heavy scale or soak run is required
to exercise these startup and shutdown checks.
