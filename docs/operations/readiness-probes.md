# Expose private HTTP readiness checks

Use the optional probe adapter when your local supervisor needs HTTP checks and
cannot run the authenticated `latent node get` command itself. The adapter reads
the real node inventory through that command and returns only a small status
response. It works before any publication exists and never invokes a capsule or
uses a customer's page as a probe target.

The qualified composition uses the [local container image](container-runtime.md)
and its private loopback network namespace. Managed-platform HTTP probes,
including ACA peer and revision behavior, remain unqualified. Do not expose the
operator endpoint publicly to make a health checker reach it.

## Choose the meaning of each check

| Endpoint | Success means | Use |
| --- | --- | --- |
| `/startup` | This adapter observed the intended node fully ready at least once, and still has a current healthy observation. | A one-time startup gate for this node/adapter lifetime. |
| `/live` | A current authenticated observation reports healthy native state and live HTTP listener/owner. | Detect unavailable or unhealthy backend ownership. Load alone does not cause a liveness failure. |
| `/ready` | The current node is healthy and ready, pressure is available, HTTP ownership is complete, and connection/exchange/buffer capacity has room. | Admit new static traffic. Overload returns 503. |

All checks fail before the first valid observation and after an observation is
more than three seconds old. A failed CLI call immediately clears live/ready
success. Startup success is latched separately; it does not substitute for
current readiness. A listener bound before usable catalogs and configuration is
insufficient: the adapter requires the authenticated recovered node inventory.

This profile conservatively **retains native activation readiness** for a static
node and additionally checks the real HTTP owners and spare capacity. It does
not infer static readiness solely from the activation bit. A saturated or failed
execution subsystem can therefore keep this conservative profile unready even
if some static reads might succeed. Native inventory sources are individually
coherent observations, not a transaction across every subsystem.

## Run beside the intended node

Use the same approved image and private client configuration as the node.
`ConfigDirectory` is the existing protected configuration mount and `NodeId` is
the node identity you expect. Keep the sidecar tied to that container's lifetime:

```sh
docker run --name lsf-probe --read-only --cap-drop ALL --security-opt no-new-privileges --memory 128m --pids-limit 16 --network container:lsf-node --mount "type=bind,source=$ConfigDirectory,target=/etc/lsf,readonly" --entrypoint /usr/local/bin/python3 lsf-runtime:reviewed -I /opt/lsf/runtime/probe.py --node-id "$NodeId"
```

The adapter binds only `127.0.0.1:18181`. Requests must use exactly
`Host: 127.0.0.1:18181`; unrelated peers, forwarded identity, request bodies and
ambiguous headers are rejected. GET and HEAD are supported. Responses contain
only `{"status":"ok"}` or a fixed unavailable/error status, with `no-store` and
`nosniff`. They contain no credentials, tenant inventory, publication IDs or
internal diagnostics. The CLI credential stays in its existing private file.

Your local probe caller must share that network namespace or use a separately
reviewed local edge. A different container's loopback refers to itself. Recreate
the adapter with the intended node namespace after a restart or during a
[container handover](container-handover.md), rather than leaving it attached to
the old revision. An unexpected node ID fails observation.

For private diagnosis, perform one real observation without starting a listener:

```sh
docker exec lsf-probe /usr/local/bin/python3 -I /opt/lsf/runtime/probe.py --node-id "$NodeId" --check
```

## Bound supervision and recovery

The adapter adds two node-fixed threads and at most one CLI child. It samples
once per second after the previous sample completes; each child has a 1.5-second
deadline and 256 KiB output ceiling. It never queues overlapping samples or
creates a worker for a publication or an incoming probe. HTTP handling is serial,
with a two-connection listen backlog, 4 KiB request bound, 16 headers, half-second
read/write deadlines and fixed response bodies. SIGTERM stops sampling and joins
the owned child/thread within the documented deadline.

For this local profile, poll readiness every three seconds with a one-second
HTTP timeout and remove a backend after two failures. Allow startup enough time
for actual recovery and the configured supply-chain clock lease. Keep liveness
less aggressive (for example, three failures ten seconds apart) and investigate
repeated failures before restarting; pressure and a full HTTP pool should affect
readiness, not trigger a restart loop. These are local supervision settings, not
a managed-host qualification.

The maintained test uses an empty real node, four real incomplete HTTP requests
to fill its listener capacity, actual SIGSTOP/CONT to make its management RPC
unresponsive, actual clean shutdown, a wrong node selection, an unrecoverable
durable clock file in a separate disposable installation, and real elapsed time
to expire a cached success. It recreates the adapter after the node's Docker
restart replaces its network namespace. It checks status-only responses, method/Host/forwarded-header rejection,
bounded cleanup and sampled sidecar resources. It then runs the signed-site,
restart, handover and storage-recovery checks on the same node. No successful
health response is fabricated when the backend is unavailable.
