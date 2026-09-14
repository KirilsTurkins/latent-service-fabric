# Shared provider pools

`latent_capabilities::broker::pools` implements
[#206](https://github.com/KirilsTurkins/latent-service-fabric/issues/206): one
configured provider registry per broker generation, bounded shared clients and
connections, fair request admission, and finite worker and cleanup ownership.
The registry uses the node's supplied Tokio control handle and the existing
[asynchronous I/O owner](async-host-io.md). It creates one shared control task,
with no service-specific runtime, thread, listener, retry loop or timer.

This is the common provider infrastructure. Production configuration and coherent
plan installation are [#207](https://github.com/KirilsTurkins/latent-service-fabric/issues/207).
HTTP, blob, secrets and event protocol adapters remain their separate Phase 3
tickets. Ordinary standalone startup still exposes its existing built-in imports;
declaring a capability does not construct a client or enable an external provider.

## Installation and immutable epochs

The trusted node adapter validates its protocol-specific configuration, then calls
`ProviderPools::install` with a logical provider ID, public authority identity,
exact expected epoch and credential bytes. Creation expects epoch zero;
replacement must advance the installed epoch. Public configuration digests must
exclude credentials. Credential storage is bounded and zeroizing, has no `Debug`
implementation, and is absent from pool keys, descriptors, snapshots and errors.
Only trusted adapter code can inspect the private epoch's credential bytes.

The registry reserves configuration and metadata capacity before retaining a
replacement. It validates the expected epoch and publishes atomically under the
registry fence, retiring the old broker registration before exposing the new one.
A rejected replacement leaves the old installation usable. Rotation needs room
for both epochs: old plans, accepted calls and physical connections retain their
actual reservations until destroyed.

There are three distinct identities: the configured logical provider ID, the
private monotonically allocated client/epoch instance, and a public service name.
The trusted adapter maps its approved origins to opaque integer slots. Looking up
the same typed origin slot reuses its configured client; a type mismatch or
foreign installation is rejected. Neither a service name nor a guest-provided URL
creates another pool. A second registry on the same broker generation is rejected,
including after retirement, so it cannot bypass a lowered ceiling.

## Finite capacity and fair admission

Defaults and absolute capacity ceilings are:

| Resource | Default | Absolute ceiling |
| --- | ---: | ---: |
| Retained configurations | 32 | 256 |
| Configured clients/origins | 128 | 1,024 |
| Clients per provider | 8 | 128 |
| Connections, including reserved dials | 256 | 4,096 |
| Connections per client | 8 | 256 |
| Idle connections | 64 | 1,024 |
| Pending requests | 128 | 1,024 |
| Running/retained request owners | 64 | 1,024 |
| Requests per tenant | 32 | 1,024 |
| Requests per logical provider | 64 | 1,024 |
| Running requests per tenant/provider | 16 / 32 | 1,024 each |
| Provider workers / cleanup jobs | 16 / 8 | 128 each |
| Accounted registry metadata | 8 MiB | 64 MiB |
| Copied private configuration bytes per epoch | 64 KiB | 1 MiB |

Cross-limit constraints also apply. `lower_limits` cannot raise startup limits,
erase outstanding reservations, or lower a per-client/provider/tenant ceiling
below its actual use. Checks include retired epochs and clients retained by old
calls. Client/request/running limits aggregate all retained epochs of the same
logical provider; credential rotation cannot create another fairness allowance.
Shorter queue and idle ages apply to future admissions and idle reuse;
an admitted request keeps its original absolute deadline. Backoff parameters are
fixed for the registry generation. Quotas are ownership bounds, not total RSS
limits: concrete protocol adapters must also account for their buffers and driver
resources through the I/O and worker owners.

`admit` reserves queue and metadata space before staging input. Its tenant comes
from the sealed execution plan. The queue rotates between tenants, then providers
within a tenant, with FIFO ordering within each group. A tenant cannot acquire
extra turns by using many providers. Tenant and provider running ceilings prevent
one group from occupying the entire configured pool. Waiters have finite ages
(five seconds by default, at most one minute), narrowed by the original Store and
I/O deadlines. Both queue stages share those deadlines; waiting never resets them.

After capacity becomes ready, the adapter performs a fresh broker dispatch and
passes the accepted `ProviderCall` to `PoolReady::start`. The exact session,
ledger, provider and epoch must match. A revoked policy or retired provider cannot
authorize a later start. Work accepted before an individual epoch's retirement
may finish with that immutable configuration, subject to cancellation, deadlines
and node shutdown. Capacity alone never supplies execution permission.

Pool request ownership is attached to the same I/O operation as its buffers and
streams. Delayed consumers, blocked jobs and partial results therefore retain
tenant/provider capacity and the original activation after the caller returns.
Cancelling a queued future does not refund input buffers still held elsewhere.

## Connections, backoff and cleanup

`reserve_connection` charges before dialing. There is at most one simultaneous
dial per configured client. A failed or cancelled dial records bounded exponential
backoff: initially 100 milliseconds, capped at 30 seconds by default. Admission
returns a fixed unavailable/busy/capacity error during backoff or saturation.
The registry never retries an application operation or initiates a reconnect;
the caller explicitly decides whether a later attempt is appropriate.

`PooledConnection<T>` destroys the actual resource before releasing its connection
charge. During active use or dialing it also retains the original activation's
I/O owner. `T` must own the real connection: a facade for a detached driver is
insufficient. Such drivers need their own bounded provider jobs and ownership.
Only a protocol adapter that has verified a reusable connection may park it.
Cancelled activations, failed cleanup and retired epochs cannot refill idle pools.
Idle sockets retain shared node capacity without retaining an activation. Their
default idle age is 30 seconds, with a one-hour absolute maximum. Checkout checks
expiry itself; the single control owner also reclaims expired or retired idle
entries in bounded scans.

`spawn` and `spawn_blocking` reserve worker and metadata space before constructing
or submitting work to the supplied runtime. The fixed task inventory retains
join handles until actual completion. Dropping a result waiter does not abort a
blocking job or release its leases. Cleanup has separate reserved capacity, so
ordinary workers cannot consume every cleanup slot. Successful cleanup destroys
the resource; failed cleanup returns the still-owned, charged connection for
explicit recovery or destruction. A failed close never invents a refund.

## Shutdown and observations

`retire` closes new admission, stops the shared I/O owner and retires installed
epochs. The control task drains idle resources and joins finished jobs. `shutdown`
waits within the supplied deadline, returning a snapshot of remaining ownership
on timeout. It neither aborts noncooperative blocking work nor claims its resources
were reclaimed. The supplied runtime must remain alive through this drain.

Snapshots contain aggregate counts only: configured and retained epochs, clients,
active/idle/connecting/retired connections, pending/running request owners, workers,
cleanup, failed cleanup and accounted metadata. They are observational rather
than an atomic admission decision. `is_clean` additionally requires completed
control ownership and no control failure. An interrupted control owner closes
admission and cannot produce a clean shutdown report. Retained configuration
references alone do not represent an active socket, worker or activation.

## Validation

`cargo test -p latent-capabilities --lib --locked` covers real loopback socket reuse
and EOF after closure, tenant/provider fairness, saturation and live lowering,
atomic credential rotation, queued revocation, cancellation with retained input
and result bytes, reconnect storms, idle expiry, failed/delayed cleanup, provider
panic, and a real blocking job whose dropped waiter cannot refund it. Tests also
check that cleanup progresses when ordinary workers are saturated and shutdown
waits for actual joins. These are bounded conformance tests, not a load campaign
or a claim of hostile multitenant qualification.
