# Bounded OCI DNS and content redirects

`HttpOciRegistry::new_with_network(config, network)` explicitly opts into the
network portion of `lsf-oci-bearer-v1`. `new_with_network_and_cache` additionally
accepts the existing shared raw artifact cache. The ordinary constructors retain
their static-address behavior. No upgrade or registry response enables DNS,
token services or storage destinations implicitly.

This profile implements [#270](https://github.com/KirilsTurkins/latent-service-fabric/issues/270)
on the [scoped bearer owner](oci-bearer-read-auth.md), under
[ADR-0029](../../adr/0029-separate-registry-authority-from-transport-profile.md).
It does not grant guest network capabilities, admit packages, establish publisher
trust or claim production/hostile-multitenant certification.

## Explicit destinations

Supply `RegistryNetworkPolicy` with at most eight `RegistryDestination` entries.
Each entry binds one exact HTTPS origin, an address policy, either explicit
static IPs or an explicit numeric DNS server, and optional content path prefixes.
Both the registry and configured token realm must have approved entries. They
may share an origin, but the exact token URL remains separately bound by bearer
policy. Duplicate origins, unknown destinations and partial policies fail closed.

The selected network constructor requires `BearerChallenge`, empty legacy
`RegistryConfig.addresses` and token `addresses`, and verified HTTPS. It rejects
`allow_insecure_loopback`; the static test profile remains separate. TLS uses the
original origin hostname, the pinned root set and explicitly supplied DER roots,
never an IP substituted for the certificate name.

For example, with a bearer config approving `https://registry.example/token`:

```rust
use latent_oci::{
    HttpOciRegistry, RegistryAddressPolicy, RegistryDestination,
    RegistryNetworkPolicy, RegistryResolution,
};

let network = RegistryNetworkPolicy {
    destinations: vec![RegistryDestination {
        origin: "https://registry.example".into(),
        addresses: RegistryAddressPolicy {
            networks: vec!["203.0.113.20/32".parse().unwrap()],
            special_addresses: vec!["203.0.113.20".parse().unwrap()],
        },
        resolution: RegistryResolution::Dns {
            server: "192.0.2.53:53".parse().unwrap(),
            maximum_ttl_seconds: 30,
        },
        content_prefixes: Vec::new(),
    }],
    maximum_redirects: 0,
};
let registry = HttpOciRegistry::new_with_network(config, network)?;
```

These are documentation-only addresses, not live infrastructure. Replace all
identities with operator-approved values. Documentation/private/loopback,
link-local, metadata and other special ranges require an **exact**
`special_addresses` opt-in as well as an allowed CIDR. A broad CIDR alone never
permits them. IPv4-mapped IPv6 is canonicalized before either check. Policy has at
most 16 CIDRs and 16 special addresses. Static resolution has at most 16 addresses;
a literal origin cannot be remapped to a different IP.

## Resolver and connection bounds

`latent-network` contains the capability-independent address and DNS parsing
primitives shared with the outbound HTTP provider. The registry does not import
the provider's guest grants. Resolution uses only the configured server, with
bounded UDP and same-server TCP fallback for truncated answers. It does not read
system resolver configuration, environment proxies or credential helpers.

- One coalesced acquisition and one fixed eight-address cache per DNS destination.
- At most `max_in_flight` admitted resolver callers per destination, hard maximum
  32; no unbounded wait queue or background resolver/refresh worker.
- A and AAAA queries, at most five exchanges each, bounded CNAME chains and cycle
  rejection; 4096-byte packets, at most 16 answer and eight authority/additional
  records per section. Oversized TCP length prefixes fail before allocation.
- TTL is the minimum observed chain TTL and operator ceiling, at most 300 seconds.
  Zero TTL disables reuse; expired entries are discarded on demand.
- Every answer must pass destination policy. Every connected peer must both
  belong to that answer set and pass policy again before TLS or HTTP bytes.
- HTTP/1.1 only, no idle pool, compression, ambient DNS, automatic transport retry
  or independently spawned connection driver. The response owns its socket,
  TLS state and Hyper driver directly.

The original absolute transfer deadline covers DNS, connect, TLS, token exchange,
content redirects and response bodies. Connect/request limits only shorten it.
A slow peer or another hop cannot refresh the operation budget.

## Redirect classes and credentials

Only bodyless GET/HEAD of a repository blob digest can begin a content redirect.
Statuses 301, 302, 303, 307 and 308 preserve the read method. The configured hop
limit is zero through three, with 4096-byte URLs and cycle detection. Each target
must match an approved origin and an explicitly approved storage path prefix.
Prefixes end with `/`, cannot be `/v2/`, and have finite grammar/count/length.

Redirects reject userinfo (including empty userinfo), fragments, encoded paths,
dot segments, scheme downgrade, another repository, the configured token endpoint
and unapproved storage paths. Query bytes remain bounded opaque data, not logged
authority. All follow-ups omit registry authorization, cookies and token-service
Basic credentials, **including same-origin storage redirects**. A storage `401`
does not trigger token acquisition or credential forwarding.

Token endpoints never follow redirects. Mutations never follow HTTP redirects or
retry after uncertainty. Upload `Location` is a distinct same-origin,
same-repository session continuation, not a storage redirect: the existing opaque
query and digest-finalization rules remain unchanged. Referrer pagination also
retains its existing origin/repository/subject checks. Final content length,
descriptor digest and evidence association checks apply after allowed redirects.

## Physical ownership and shutdown

`RegistryUsage.network` exposes active connections, reserved connection bytes,
configured connection ceilings, active/waiting resolvers, retained DNS answers,
resolver bytes and redirect-history reservations. These are bounded ownership
reservations, not measured process RSS or an exact operating-system socket-memory
accounting claim. Configuration/TLS roots and fixed cache slots remain part of
the bounded shared client, including after shutdown until that client is dropped.

Connections are capped at `max_in_flight + 1`, reserving 256 KiB each plus retained
request bytes, within `max_retained_bytes + connection_slots * 256 KiB`. Active DNS
work reserves 64 KiB plus its fixed cache slot. A redirect owner reserves 16 KiB.
Requests allow at most 32 headers/16 KiB; responses allow 100 headers/16 KiB with a
32 KiB parser ceiling, finite body limits and 65,536 frames. Trailers are rejected.

Dropping a DNS or foreground transfer future drops its actual socket/driver before
its lease is refunded. A retained response or ongoing upload cleanup remains
charged. Shutdown closes new admission, waits for active operations and cleanup,
closes resolver caches, then waits for retained connection owners. A shutdown
deadline reports failure without pretending outstanding work was reclaimed.

Upload initiation already handed to the shared worker remains owned until its
original deadline so a late session URL can be safely recovered. An abandoned
known session transfers to the previously reserved, finite cleanup queue: its
DELETE has the existing independent `cleanup_timeout`, not a renewed upload
budget or a retry of an uncertain mutation. Cleanup failure remains observable.
An unknown remote session cannot be deleted locally; registry-side expiry is
required, and shutdown does not claim otherwise.

## Maintained conformance and limitations

The named matrix is Zot minimal 2.1.18 with `lsf-oci-static-v1` and Harbor 2.15.2
with `lsf-oci-bearer-v1`. Distribution 3.1.1 remains excluded from the complete
native-referrer evidence profile; no mutable fallback is implemented.

```sh
cargo test -p latent-network -p latent-oci --all-targets --locked
python -m unittest tools.tests.test_harbor_registry_runner
python tools/run_oci_registry_tests.py
python tools/run_harbor_registry_tests.py --network --output target/harbor-network.json
```

Harbor uses the digest-pinned images in
[`images.json`](../../tools/harbor_registry/images.json), the hash-verified 2.15.2
installer template, private disposable project, fresh pull/push robot credential,
ephemeral TLS and one owned loopback DNS server for `harbor.test`. The server
never forwards arbitrary DNS. It maps only that fixture name to explicitly
approved loopback; omitting the special-address grant proves denial against the
same real topology before connecting. No hosted provider credentials are needed.

The real fixtures prove tiny authenticated package/evidence uploads, digest-pinned
pulls, native referrers, denied authority and owned-resource removal. Harbor's
local-storage topology **does not issue object-storage redirects**. Approved and
denied redirect paths, credential stripping, loops, digest corruption, slow
responses, TLS/DNS/token cancellation and retained upload cleanup are tested with
controlled TLS/DNS peers, not mislabeled as a hosted object-store certification.

Receipts retain package/evidence digests, image/installer identities, DNS query
counts, denial/cleanup results and source identity. A clean committed-head run is
required for reviewed evidence. Supplied test binaries are hashed but explicitly
do not establish source correspondence. Working-tree diagnostics are not release
evidence. The broader HTTP integration fixtures require Linux durable catalogs;
Windows can run the shared parser/address and registry tests, not substitute for
that Linux integration coverage. PR CI runs deterministic tests; the owned Harbor
invocation is explicit conformance evidence, not an implicit hosted-service check.
