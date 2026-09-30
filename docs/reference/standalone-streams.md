# Development outbound TCP installation

Outbound stream installation currently requires a Linux x86_64 node built with
`development-outbound-streams`. Ordinary builds reject this configuration. The
profile remains subject to [ADR-0061](../../adr/0061-bound-standard-outbound-streams.md)
review and [qualification gates](../runtime/outbound-stream-qualification.md).

The node reads immutable destination facts from its existing protected JSON
configuration. Protect the parent directory with mode `0700` and the file with
mode `0600`, using the existing standalone configuration loading path. Configuration
derivation checks the exact endpoints and addresses without opening a socket or
creating node storage. Startup installs the original capability broker and bounded
provider pools without creating a guest Store or contacting any destination.

This complete minimal configuration selects one explicit local TCP peer. Replace
the example administrator token before starting a node. A stream binding and
provider installation grant no guest access: the normal capability administrator
must separately authorize exact stream operations and endpoints for the selected
deployment. Empty capability policy state denies guest requests.

```json
{
  "formatVersion": 1,
  "dataDirectory": "data",
  "nodeId": "stream-development-node",
  "credentials": [{"token": "replace-with-at-least-32-random-bytes", "subject": "administrator", "tenant": "examples", "role": "admin"}],
  "budgetProfile": {"mode": "phase3", "maximumOutboundRequests": 8},
  "capabilityPolicies": {"formatVersion": 1},
  "audit": {"mode": "durable"},
  "providers": {
    "formatVersion": 1,
    "outboundStreams": {
      "identity": {"id": "streams", "tenant": "examples", "service": "stream-host", "epoch": 1},
      "configuration": {
        "formatVersion": 1,
        "profile": "lsf-outbound-streams-v1",
        "destinations": [{
          "endpoint": {"host": "127.0.0.1", "port": 32123, "transport": "tcp"},
          "addresses": {"networks": ["127.0.0.1/32"], "specialAddresses": ["127.0.0.1"]},
          "resolution": {"kind": "static", "addresses": ["127.0.0.1"]}
        }],
        "limits": {"maximumTransferBytes": 65536, "idleTimeoutMillis": 1000, "absoluteTimeoutMillis": 5000}
      }
    },
    "bindings": [{"name": "stream-binding", "tenant": "examples", "consumerService": "guest-stream", "providerService": "stream-host", "contract": "latent:network/streams@0.1.0", "providerBinding": "streams-installed"}]
  }
}
```

The exact special-address exception above applies only to the selected loopback
IP. A broad CIDR never grants loopback, private, link-local or metadata access on
its own. DNS configuration requires an explicit resolver peer and bounded TTL;
ambient resolver discovery and proxy settings do not apply.

TCP payload is opaque. Guest TLS and application authentication belong to the
selected language runtime and independently authorized secret capabilities.
This slice rejects host TLS installation and accepts no host key paths, trust
directories, environment lookup or plaintext application credentials. Node
administrator credentials remain protected by the existing configuration owner.

Retirement fences the provider and cancels its original I/O owners. Shutdown
reports stream owners, physical connections, pending operations and retained
chunks alongside existing provider-pool and I/O snapshots. A clean result requires
all actual stream owners to be zero. The shared lifecycle implementation supports
bounded rotation and drain with old-owner retention; authenticated live operator
rotation and packaged-node qualification remain tracked in #739.
