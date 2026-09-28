# Serve a static site through a local HTTPS edge

Use this profile when a dedicated Linux host needs TLS termination in front of
the native trusted-proxy listener. You get one HTTPS authority with root and
mounted static publications. The edge preserves native browser policy and
publication checks. If you do not need a separate edge, use
[native TLS](../reference/http-ingress.md) directly.

This guide qualifies local Linux networking. ACA ingress peers and managed-cloud
routing are unqualified; no Azure resources or cloud simulation are involved.

## Configure the native listener

Prepare the [non-root native container](container-runtime.md), private local
storage and the [readiness adapter](readiness-probes.md). Set the application
listener to `127.0.0.1:18080` and the transport to:

```json
{"mode":"trusted-proxy","peers":["127.0.0.2"]}
```

Keep the node and edge in one protected Linux network namespace. Permit no
unrelated workloads there. The edge always connects from `127.0.0.2`; a connection
from ordinary `127.0.0.1` is denied. A host administrator can control those
addresses, so this topology does not isolate the node from that administrator.

Configure the public-origin authority and static GET/HEAD trigger scheme as
`https`. Include the public port in the authority if it is not 443, for example
`frontend.example.test:18443`. Host identifies the configured tenant; paths are
mounts within that authority, not tenant isolation. Keep management on its own
literal-loopback endpoint.

## Build and configure the edge

The edge image pins Node.js 24.19.0 and its source files:

```sh
docker build --tag lsf-edge:reviewed --file tools/trusted_edge/Dockerfile .
```

Create a separate private directory owned by UID/GID 10001, mode 0700. Put your
certificate chain in `tls/server.pem` and its private key in `tls/server-key.pem`,
with the `tls` directory mode 0700 and files mode 0600. Use a certificate issued
for your exact public hostname. Test-generated identities are not deployment
certificates. Give the edge this directory only; do not share operator credentials.

Save the following canonical JSON as `edge.json`, mode 0600. Keys are sorted and
there are no insignificant spaces; adjust the authority and bind deliberately:

```json
{"authority":"frontend.example.test:18443","bind":"0.0.0.0","certificate":"/etc/lsf/tls/server.pem","formatVersion":1,"port":18443,"privateKey":"/etc/lsf/tls/server-key.pem","upstreamPort":18080}
```

`EdgeDirectory` is that absolute protected directory. With the native container
already running as `lsf-node`, run:

```sh
docker run --name lsf-edge --read-only --cap-drop ALL --security-opt no-new-privileges --cpus 1 --memory 192m --pids-limit 32 --network container:lsf-node --mount "type=bind,source=$EdgeDirectory,target=/etc/lsf,readonly" lsf-edge:reviewed
```

For a host-networked native node, the edge uses that same host namespace. For an
isolated native namespace, publish only the edge's public port on the owning
container when it is created. Do not publish ports 18080, the private readiness
port or management. Configure bounded log rotation in the Docker daemon.

## Verify a publication

Publish and route your signed site using the [static release workflow](static-release-workflow.md).
Check HTTPS using your normal certificate trust, including GET and HEAD at both
`/` and any mount such as `/docs/`. Native responses retain CSP, `nosniff`, the
same-origin resource policy and HSTS. Directory redirects retain the mount.
An external-origin request can still be rejected by native browser policy;
the edge never removes Origin or Fetch Metadata to make it succeed.

The edge accepts bodyless GET/HEAD and one authority. It rejects forwarding,
platform identity and deadline headers, upgrades, duplicate headers and request
bodies. It does not provide arbitrary API proxy rules. The `/__lsf/` prefix is
reserved and rejected; health checking uses the private adapter's actual `/ready`,
`/live` and `/startup` paths on port 18181, never a customer page or a TCP-only test.

## Restart and inspect limits

Follow [exclusive container handover](container-handover.md). Stop the edge and
probe before replacing or restarting the native owner. Once the node has
recovered, recreate both dependent containers in its current network namespace.
Starting an old sidecar again can leave it attached to the previous namespace.
Verify private readiness and exact publication bytes before routing traffic.

The edge holds at most 16 connections and eight active exchanges. Headers are
limited to 32 fields and 8 KiB, responses to 8 MiB. It uses two-second handshake,
header and idle limits and a five-second total lifetime. Response streaming has
backpressure, with no queue, content cache or mutation retry. Slow or disconnected
clients lose the connection; capacity returns after both directions close.
Native resource limits remain independently authoritative.

The maintained CI drill records both Docker's memory/CPU/task sample and process
RSS, plus restart duration. These are different accounting views and samples,
not latency or throughput guarantees. A local run observed 19.90 MiB Docker
memory, 11 tasks and 0.09% CPU at the sampling instant; restart through verified
HTTPS took 11.827 seconds. Use the current CI receipt for the image and host being
evaluated. Runtime restarts are separate from ordinary publication updates.

See the [architecture decision](../../adr/0057-pin-a-local-https-edge-to-an-exact-native-peer.md)
for the trust and qualification boundaries.
