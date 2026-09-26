# Bounded OCI registry adapter

`latent-oci::HttpOciRegistry` transfers exact package bytes through one
operator-approved registry origin and repository. It supports package push,
tag/digest resolution, manifest/blob pull, complete package pull and native OCI
1.1 referrer discovery. Capsule, browser-assets, SSR and detached-evidence
envelopes use the [package format](../protocol/package-format.md).

This Rust library handles registry transport. The
[packager](../component-development/packaging.md) checks package structure and
supplied component semantics; node admission checks publisher, build and SBOM
evidence before making a publication eligible. For application delivery, use
the [static-site](../component-development/static-sites.md) or
[Angular](../learn/build-and-deliver-angular.mdx) workflow.

The separate [publisher verifier](publisher-trust.md) can authenticate pulled
signature evidence against explicit current policy/revocation snapshots. The
[builder verifier](build-provenance.md) authenticates provenance through separate
builder anchors and source requirements. Neither result admits a catalog release.

## Versioned transport profiles

[ADR-0029](../../adr/0029-separate-registry-authority-from-transport-profile.md)
and [RFC-0003](../../rfcs/0003-versioned-oci-transport-profiles.md) separate the
registry's permanent authority/ownership boundary from transport interoperability
choices.

`lsf-oci-static-v1` is the supported profile for static credentials and addresses:

- one explicit HTTPS origin and repository;
- operator-supplied socket addresses for hostname origins, with no runtime DNS;
- anonymous, explicit Basic or preissued Bearer credentials;
- no token-service exchange or refresh;
- no HTTP redirects; upload locations and pagination continuations remain within
  the existing origin/repository rules;
- native OCI 1.1 referrers only; no mutable legacy referrers-tag fallback.

`lsf-oci-bearer-v1` has an implemented
[bounded authentication layer](oci-bearer-read-auth.md): challenge parsing,
coalesced token acquisition/refresh, explicit identity/credential epochs and
preauthenticated writes without replay. Its explicit
[network policy](oci-network-profile.md) adds bounded DNS, connected-peer checks
and authorized credential-free content redirects, with real topology conformance.
Static credential callers remain on the static profile; an upgrade does not
silently authorize DNS, token services or redirect targets.

The support matrix names the exact demonstrated fixture topologies:

| Registry/version | Profile | Authentication/topology | Push/pull | Native referrers | Current status |
| --- | --- | --- | --- | --- | --- |
| Zot minimal 2.1.18, pinned `sha256:f1ffb7a5bbddc0feea83646e29c587ecf39b3193733b447749d4c9ead111a395` | `lsf-oci-static-v1` | ephemeral TLS loopback origin, explicit Basic credential | demonstrated | demonstrated | supported repository fixture |
| Harbor 2.15.2 | `lsf-oci-bearer-v1` | private project, approved same-origin token realm, explicit DNS and verified TLS; local storage | demonstrated | demonstrated | supported owned fixture; storage redirects separately tested with controlled TLS peers |
| Distribution 3.1.1 | no complete LSF evidence profile | deployment-specific | package transfer can interoperate | unavailable in the currently documented tested surface | explicit complete-profile exclusion |

The Harbor fixture records exact release/container and source identities, uses
disposable TLS, a private project and least-privilege credentials, bounds local
container resources, and destroys only resources it owns. It proves exact push,
digest-pinned pull, native referrers and denied DNS authority. Its local storage
does not prove compatibility with hosted object-storage redirects: see the
[precise network evidence boundary](oci-network-profile.md#maintained-conformance-and-limitations).
No mutable fallback is authorized.

Permanent rules apply to every profile: server-controlled challenges, DNS replies,
redirects, links and manifests cannot grant endpoint or credential authority;
all continuations consume one original operation deadline; physical network,
buffer, cache and cleanup work stays charged until retirement; uncertain writes
are not blindly replayed; and successful transfer/discovery is not publisher
trust or catalog admission.

## Configure the endpoint

Static credential variants select `lsf-oci-static-v1` behavior. The explicit
`BearerChallenge` variant selects the bounded authentication extension described
in [its reference](oci-bearer-read-auth.md).
Construct the client inside a Tokio runtime with `RegistryConfig`. `origin` is
an HTTPS origin, including an optional port, without credentials, a path, query
or fragment. `repository` is one permitted OCI repository. Every `OciReference`
must match that repository and the origin's authority exactly; its `registry`
field omits the scheme. Reference names are valid OCI tags or canonical lowercase
SHA-256 digests. Use explicit digests for durable identity.

For hostname origins, supply up to 16 approved `SocketAddr` values in `addresses`,
using the origin's port. The static profile performs no runtime DNS lookup.
Literal IP origins can leave this list empty. Certificate chain and hostname
checks remain enabled. Trust roots are the pinned Mozilla root set plus up to
eight explicit DER roots, each at most 64 KiB. It does not install roots globally
or consult network certificate services.

Choose `RegistryCredentials::Anonymous`, explicit Basic credentials, or a
preissued Bearer token. Credentials are scoped to this client and redacted from
its diagnostic representations. The static profile has no automatic token-service
exchange, credential refresh, credential helper or implicit environment-proxy
support. Obtain or refresh tokens outside this adapter and construct a new
configured client when needed. Authentication failures remain errors.

The Bearer extension never makes a registry-supplied realm authoritative. Its
configuration separately approves the token authority, service/audience,
repository/actions, tenant, principal and credential epoch. Hostname destinations
require explicit addresses with the ordinary constructors. Only the separate
`new_with_network` policy enables bounded DNS and approved content redirects;
unknown or unavailable behavior does not gain network authority.

HTTPS is the normal transport. `allow_insecure_loopback` permits HTTP only for a
numeric loopback address when explicitly enabled for local tests. It cannot
disable HTTPS certificate validation. The integration fixture uses verified
HTTPS and leaves this option disabled.

## Identity and ownership

`pull_package` fetches a tag's manifest once, calculates its exact immutable
digest, then follows the associated config and layers. Moving the tag cannot
substitute another package during that pull. Descriptor sizes, hashes and
envelope media types are checked before the complete request is exposed.
Content hashing uses received bytes without JSON reserialization.

The returned `OciPulledPackage` exposes a borrowed `request()` and keeps its
package slot and raw-byte lease until dropped. Copying application data out of
that borrow creates caller-owned retention. Low-level `pull_manifest`,
`pull_blob`, `resolve` and `list_referrers` likewise transfer their returned
buffers/metadata to the caller; a caller retaining many results must impose its
own aggregate budget. These limits are not a process-RSS guarantee.

`push` consumes a fully associated `OciPushRequest`, checks existing blobs,
uploads missing config/layers and publishes the original manifest last. The
returned digest must equal the supplied manifest's exact digest. Repeating a
completed push is idempotent. There are no automatic transport retries; callers
must decide whether and when to retry within their own larger operation budget.
An uncertain final response may require checking the immutable digest before
repeating publication.

The shared upload worker retains initiation and cleanup ownership when a caller
cancels. Known abandoned sessions receive a bounded cleanup attempt; capacity
remains charged while that work is owned. If the connection fails before the
registry returns its session URL, the adapter cannot identify that remote
session, and registry-side expiry must reclaim it. Shutdown closes admission and
waits for owned work until the supplied deadline; a deadline error does not
claim that remote cleanup completed.

Token acquisition, DNS, redirects and upload continuations consume the same
original absolute operation deadline. `connect_timeout` and `request_timeout`
are inner ceilings, not fresh budgets after each continuation. An abandoned
known session transfers to the previously reserved cleanup owner, whose DELETE
has the separate bounded `cleanup_timeout`; this cannot resume the upload or
replay an uncertain mutation. Resolver work, token cache entries, sockets,
redirect metadata and cleanup remain charged until actual retirement or that
explicitly bounded ownership transfer.

## Optional raw download cache

`HttpOciRegistry::new_with_cache` accepts a shared
[`RawArtifactCache`](raw-artifact-cache.md). Complete package pulls can reuse
verified blob payloads while retaining their ordinary manifest, descriptor and
output-budget checks. The manifest is still fetched remotely on every pull, and
each cached blob requires an authorized `HEAD` with the exact advertised length
and a matching digest header when present. `405`/`501` fall back to ordinary
authenticated `GET`; an authorization failure remains an error. Low-level reads
and referrer discovery keep their existing behavior.

Reclaimable entry/disk/metadata pressure receives one reclamation pass of at most
16 examined entries and one reservation retry, then remains an explicit error.
Non-reclaimable limits or contention do not evict data. Cache reservations and split OCI buffer permits
move into blocking file work together, so caller cancellation cannot refund
capacity before that work ends. `cache_usage()` reports the configured cache's
aggregate storage and ownership counters. Catalog admission and execution
eligibility remain separate from download caching.
Disk results received after the absolute operation deadline are rejected even
when the job has already completed. A timeout does not forcibly stop kernel I/O
or refund its still-owned reservations.

## Supported discovery profile

Referrer listing is bounded and filtered locally by `artifactType`, even when a
registry ignores the requested filter. Descriptors remain untrusted discovery
metadata. Fetch each evidence manifest by its digest, verify its exact bytes and
its subject association, then apply the separate required trust policy.

The delivered static profile requires the native OCI 1.1 referrers API. An
unsupported API fails explicitly; it is not reported as a successful empty
evidence list. Legacy referrers-tag fallback is not implemented, so this is a
documented restricted distribution profile rather than a full OCI legacy-fallback
client. The
[OCI specification](https://github.com/opencontainers/distribution-spec/blob/v1.1.1/spec.md#unavailable-referrers-api)
defines that fallback and its concurrent-writer caveat.

Distribution 3.1.1 does not expose that native API and therefore does not support
this adapter's complete evidence-discovery profile. Package transfer alone can
work, but that must not be mistaken for complete supply-chain registry
compatibility. The real static-profile integration fixture uses Zot minimal
2.1.18 for the complete profile.

Redirects are disabled in `lsf-oci-static-v1`. Upload `Location` and pagination
`Link` URLs must remain within the approved origin/repository and the relevant
operation path. Opaque upload query parameters are preserved. Registries that
require object-store redirects or a separate automatic token origin require the
explicit `lsf-oci-bearer-v1` configuration described in the
[authentication](oci-bearer-read-auth.md) and
[network](oci-network-profile.md) references. Support remains limited to the
demonstrated topologies in the matrix above.
A challenge or redirect URL alone never grants authority to forward credentials.

## Default limits

`RegistryLimits` permits bounded configuration, while the v1 package ceilings
can only be lowered. Admission fails promptly when a shared budget is exhausted.

| Budget | Default |
| --- | --- |
| Concurrent operations | 4 |
| Retained complete packages | 2 |
| Adapter-owned raw bytes | 512 MiB |
| Referrer pages / descriptors | 8 / 256 |
| Aggregate referrer response bytes | 1 MiB |
| Connect / request / whole operation | 5 s / 30 s / 300 s |
| Upload cleanup attempt | 5 s |
| Package JSON document | 256 KiB |
| Package layers / single layer / total layers | 256 / 64 MiB / 256 MiB |

URLs are capped at 4096 bytes; retained response headers are capped at 100 entries
and 16 KiB. The pinned HTTP/1 implementation also has finite parser scratch
limits, separate from the retained-body accounting. Compression and automatic
retries are disabled; the static profile also disables redirects. `usage()` reports active operations, retained
package leases, charged raw bytes and whether admission is closed.

The Bearer profile also bounds resolver jobs and cached answers, token
acquisitions and retained token bytes, redirect hops and metadata, and connection
ownership. The [authentication](oci-bearer-read-auth.md#rotation-and-physical-ownership)
and [network](oci-network-profile.md#physical-ownership-and-shutdown) references
give those ceilings. Clones share these resources rather than allocating an
independent pool for every deployment.

## Run the real registry check

Run the maintained qualification runner on Linux x86_64 with Docker, OpenSSL
and the [pinned Python/Rust toolchain](../development/toolchain.md). Preflight
checks the environment before compilation. Prepare the exact test executable
and pass Cargo's resulting inventory to the execution-only runner:

```bash
set -euo pipefail
docker pull ghcr.io/project-zot/zot-minimal-linux-amd64@sha256:f1ffb7a5bbddc0feea83646e29c587ecf39b3193733b447749d4c9ead111a395
python3 tools/run_oci_registry_tests.py --preflight
mkdir -p target/oci-review
cargo test -p latent-oci --test registry --locked --no-run \
  --message-format=json,json-render-diagnostics > target/oci-review/registry-tests.jsonl
python3 tools/run_oci_registry_tests.py \
  --test-manifest target/oci-review/registry-tests.jsonl
```

The runner uses the pinned Linux/amd64 Zot minimal 2.1.18 image, with no scanner
or other optional registry extensions. It generates a fresh short-lived test CA/server certificate, mounts a
precreated public test-only bcrypt credential, and uses one ephemeral IPv4
loopback port. The container has 256 MiB memory, 64 PIDs, one CPU and 128 MiB
temporary registry storage, with no persistent data volume. Readiness and test
execution have finite deadlines. Normal exit/failure removes only the verified
container owned by that run, then removes its temporary files. CI also retains a
small ownership recovery record until an unconditional cleanup step completes;
an unavailable Docker daemon is reported as a cleanup failure.

The ignored Rust integration target exercises all three package kinds, exact
manifest/config/layer round trips, repeated push, movement of a tag after digest
resolution, native detached-evidence discovery/filtering, missing/wrong
credentials and rejection of an untrusted TLS root. It also generates an ephemeral
signing key, signs a package, attaches/discovers/pulls the exact evidence and
verifies it against an independently supplied publisher policy. No private key
is retained. The original tiny format corpus makes no runnable-guest or
trusted-evidence claim. Scripted HTTP unit tests cover hostile
responses and cancellation separately. The runner records bounded execution
and cleanup diagnostics. The maintained process owner requires Linux;
parser/library tests on another host do not replace this qualification. The
cold/warm/reopened raw-cache roundtrip exercises directory durability inside the
same primary integration test and uses the tiny browser package; it builds or
invokes no guest.

The optional `--test-binary` argument must match the executable selected by
`--test-manifest`; it cannot replace the inventory. Without `--provenance-input`, the separate observed-build
provenance test is skipped. The Python fixture runner and test process must share
access to the fixture's loopback endpoint and CA file; a Linux test binary in a
separate container does not share the Windows host's loopback automatically.

The separate Harbor 2.15.2 workflow exercises the Bearer profile with a private
project and native referrers. Use the
[owned Harbor workflow](oci-bearer-read-auth.md#validation-and-remaining-transport-boundary)
and its [DNS variant](oci-network-profile.md#maintained-conformance-and-limitations)
for those checks. Its results do not qualify an untested hosted-storage topology.
