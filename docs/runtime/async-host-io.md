# Bounded asynchronous host I/O

`latent_capabilities::broker::io` implements the shared ownership substrate for
[#205](https://github.com/KirilsTurkins/latent-service-fabric/issues/205). A single
configured `IoRuntime` provides finite admission, byte accounting and streams on
the caller's existing runtime. It creates no executor, thread, socket, worker,
retry loop or service-specific resource. Dormant deployments own none of these
leases. The [shared provider registry and pools](provider-pools.md) build on this
ownership. [Buffered HTTP](outbound-http.md), [streaming HTTP](streaming-http.md),
[local blobs](local-blobs.md), [S3 blobs](s3-blobs.md) and [local secrets](local-secrets.md) install concrete adapters on this substrate; the other providers are tracked
separately. Declaring an import does not install a provider.

## Admission and the original activation owner

The trusted adapter calls `IoRuntime::admit` with the broker's original
`CapabilitySession`, before staging input or waiting for shared capacity. Queue,
operation and metadata charges precede allocations. The waiting owner retains
the original session, ledger and precise monotonic Store deadline; an unbounded
deadline is rejected. It cannot execute provider work.

`IoAdmission::wait` uses the shared semaphore's FIFO queue. Both the number of
waiters and their maximum age are bounded. Saturation rejects promptly, without
spawning a worker or repeatedly rejoining the queue. Once ready, the adapter
re-enters `CapabilitySession::dispatch` to check current policy, provider and
publication authority, then passes the affine call to `IoReady::start`. A call
from another session, even one using the same identifiers, is rejected. This
transition installs the running owner before releasing the waiting owner.

The adapter moves `IoCall` into the actual provider future or an existing bounded
blocking job. Dropping a response waiter is not evidence that the job ended.
The call, its staged inputs, buffers and streams retain the running slot and
activation ownership until their actual destruction. There is no unbounded
cleanup queue, filesystem I/O in a destructor or automatic transfer to a worker.

## Deadlines, cancellation and waiting

`admit_until` can narrow the Store deadline using an operation timeout converted
once on entry. Widening it is rejected. `IoCall::deadline` also respects a tighter
provider-policy deadline. DNS, connect, TLS, body processing and adapter stages
must use this same instant; passing a fresh relative timeout after each await
would violate the contract.

`IoCall::wait_for` marks a provider wait while retaining the running slot and
activation owner. It checks cancellation and the deadline before waiting and
before delivering a result. Explicit stop and runtime retirement wake waiters;
the original execution probe is checked at bounded 10 ms intervals while waiting.
This interval bounds observation attempts, not OS scheduling latency or the
termination time of a blocking operation. A blocking adapter must retain its
lease until its worker actually returns. Cancellation does not undo an external
effect and never authorizes retry.

The internal ownership states are:

```text
Queued -> Ready -> Running <-> WaitingProvider
                     |
                     v
                  Cleaning -> Retired
```

Interrupted queue/ready owners also enter `Cleaning` if staged data remains.
The public activation stays `Running` while waiting. `IoStopHandle` is a weak
control/observation handle: it cannot refund work or retain its authority.
Streams and delayed consumers may keep an operation in `Cleaning` after its
provider future returns.

The implementation follows [ADR-0028](../../adr/0028-retain-activation-ownership-across-asynchronous-waits.md).
Wasmtime destroys the guest future and Store before calling the shared
`CapabilitySessionObserver::after_store_dropped` cleanup check. Waiting calls,
blocking work, streams and retained consumers prevent a reusable report. The
node's existing grace timeout reports quarantine if cleanup is not acknowledged.
Reclaiming a retained response later does not automatically unquarantine a cell.
Neither budget finalization nor a timeout response proves reclamation.

## Buffers, backpressure and terminal behavior

`IoBuffer` owns initialized, fixed-capacity, zeroizing storage. The adapter
reserves its capacity and protocol metadata before allocation or transport reads.
`spare_mut` exposes only the bounded unused slice; `advance_written` validates
the number actually read. No API extracts, grows or exposes a mutable `Vec`.
The charge uses vector capacity, including unused bytes, rather than payload
length. Partial consumption retains that complete charge.

The sum of bytes converted into output across all buffers/streams of a call
cannot exceed its broker-approved output ceiling. This total is cumulative:
dropping a consumer refunds live memory, not permission to produce another copy.
An input queued before provider admission cannot be converted to output yet.

`retain` reserves the result side before transferring the staged-byte charge,
without copying or creating a refund gap. If result capacity is full, it rejects
and destroys the input owner. Adapters must stop or apply explicit backpressure;
the substrate does not grow an implicit buffer or allocation queue. Protocol
metadata is an additional checked charge derived by the trusted adapter from its
actual framing; it cannot be replaced with a guest-declared size.

Each stream has one affine writer and reader and a fixed-capacity ring. A full
ring suspends the writer while retaining its pending chunk; it cannot read more
transport bytes through this operation until capacity returns. Empty chunks,
foreign-operation buffers and cumulative stream-byte overflow are rejected.
Bytes already consumed from a chunk still counted toward the stream's total
accepted bytes. Protocol adapters must separately debit their relevant cumulative
activation budgets through the broker; these shared live-byte limits do not mint
an outbound, blob or effect grant.

- EOF drains queued chunks, then returns `None` on subsequent reads.
- A provider failure, uncertain finish or oversized response drains previously
  queued chunks, then returns a sticky terminal error. The terminal reason can
  be inspected without exposing a provider error string.
- Dropping an unfinished writer marks an uncertain terminal outcome. This is
  not a durable effect receipt or a statement about remote rollback.
- Cancellation and expiry stop new delivery immediately. Closing the reader
  destroys queued chunks outside the queue lock and wakes the writer.
- A chunk already delivered to a consumer retains its bytes, stream and original
  activation owner after reader close, provider completion or caller stop.
- Destructors perform bounded memory cleanup only. They never wait for a peer,
  perform filesystem I/O, retry an operation or enqueue cleanup work.

## Limits and observations

Default shared limits are 256 operation owners, 64 occupied running slots,
128 queued calls, 8 MiB staged bytes, 8 MiB retained result bytes, 1,024 buffers,
128 streams and 4 MiB metadata. A chunk is at most 64 KiB; a stream has at most
eight queued chunks and accepts at most 64 MiB in total, additionally limited by
the call's broker-approved output ceiling (normally at most 64 KiB). Queue age is at most
five seconds and cannot exceed the activation/operation deadline. A delayed
consumer conservatively retains its running slot.

All dimensions have finite validated hard ceilings. Broker session/call limits
apply independently. Metadata charges include conservative fixed owner costs,
the stream ring's actual slot layout and declared protocol framing. Snapshots
report separate live owners, occupied slots, queued work, staged/result bytes,
buffers, streams and metadata. Individual counters can change during a snapshot;
the snapshot is observational, not an authorization or reservation operation.
These are logical ownership bounds, not total process RSS or allocator overhead.

## Executed profile and advisory boundary

The conformance harness uses the reviewed Wasmtime 47.0.4 dependency, fuel,
hostcall-fuel and a bounded Store memory limiter. Its tiny test-only component
uses an async-typed import, canonical async lowering, a real subtask and
waitable-set suspension through `func_wrap_concurrent`. It deliberately delays
both the provider and response consumer, reuses compiled code with fresh Stores,
and verifies cancellation, shutdown and the production cleanup predicate.

The original #205 substrate introduced an affine Rust stream API without
installing guest-facing providers. The current runtime can additionally install
bounded local-service, buffered/streaming HTTP and local blob adapters through
trusted ports. Streaming HTTP adds owned resources in V3; local blobs add owned
chunks in V4. Neither installs WASIp3 streams or WASI filesystem imports.
`IoJobWaiter` requests stop when its pending response is dropped; the actual
blocking worker retains `IoCall` until real completion.

The WASIp3 adapters implicated by
[RUSTSEC-2026-0268](https://rustsec.org/advisories/RUSTSEC-2026-0268.html) and the
WASI filesystem adapter in
[RUSTSEC-2026-0269](https://rustsec.org/advisories/RUSTSEC-2026-0269.html) remain
outside these installed imports. Both list 47.0.4 as a patched baseline. Each
concrete adapter must repeat this reachability review and preserve allocation
bounds. A test-only async import is not a permanent applicability exemption or
hostile-multitenant qualification. See the [host ABI profile](host-abi-profile.md)
for current interface and engine/AOT identity requirements.

Run `cargo test -p latent-capabilities --lib --locked` and
`cargo test -p latent-wasmtime --test broker --locked`. These tests need no load
campaign, external registry, language guest toolchain or persistent provider.

## Explicit bulk-transfer allowance

[Streaming HTTP](streaming-http.md) uses an explicit `CapabilityStreamBudget`.
The broker checks inline metadata plus cumulative input/output allowances at
initial and final policy admission. Only that accepted call can issue one
`IoTransfer`; dropping it cannot reset its counters. Input chunks own their
actual vector capacity, and output chunks reserve both resident storage and one
canonical lowering copy. The independent finite chunk/stream/result ceilings
remain in force. Dropping a transfer cannot refund a retained chunk or its
original activation owner. Ordinary buffered results retain their existing
cumulative inline-output ceiling.

Store resource tables reserve their backing metadata independently from a
provider call. Empty table slots therefore do not pin a running provider permit;
the table reservation still blocks a clean Store reclamation claim until actual
destruction. The guest adapter moves real resource owners out of busy entries
across waits and denies stale restoration after cancellation or resource Drop.
