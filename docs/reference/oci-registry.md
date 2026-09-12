# Bounded OCI registry adapter

`latent-oci::HttpOciRegistry` transfers exact package bytes through one
operator-approved registry origin and repository. It supports package push,
tag/digest resolution, manifest/blob pull, complete package pull and native OCI
1.1 referrer discovery. Capsule, browser-assets, SSR and detached-evidence
envelopes use the [package format](../protocol/package-format.md).

This is a library delivery boundary. It does not publish a catalog release,
authenticate a publisher, verify signature/provenance/SBOM payloads or permit
execution. Browser and SSR runtime hosting remain later work. The separately
implemented [packager](../component-development/packaging.md) checks
supplied component semantics before distribution; the registry itself cannot
make that assertion trustworthy.

The separate [publisher verifier](publisher-trust.md) can authenticate pulled
signature evidence against explicit current policy/revocation snapshots. That
library result does not by itself admit a release to the catalog.

## Configure the endpoint

Construct the client inside a Tokio runtime with `RegistryConfig`. `origin` is
an HTTPS origin, including an optional port, without credentials, a path, query
or fragment. `repository` is one permitted OCI repository. Every `OciReference`
must match that repository and the origin's authority exactly; its `registry`
field omits the scheme. Reference names are valid OCI tags or canonical lowercase
SHA-256 digests. Use explicit digests for durable identity.

For hostname origins, supply up to 16 approved `SocketAddr` values in `addresses`,
using the origin's port. The adapter performs no runtime DNS lookup. Literal IP
origins can leave this list empty. Certificate chain and hostname checks remain
enabled. Trust roots are the pinned Mozilla root set plus up to eight explicit
DER roots, each at most 64 KiB. It does not install roots globally or consult
network certificate services.

Choose `RegistryCredentials::Anonymous`, explicit Basic credentials, or a
preissued Bearer token. Credentials are scoped to this client and redacted from
its diagnostic representations. There is no automatic token-service exchange,
credential refresh, credential helper or implicit environment-proxy support.
Obtain or refresh tokens outside this adapter and construct a new configured
client when needed. Authentication failures remain errors.

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

## Supported discovery profile

Referrer listing is bounded and filtered locally by `artifactType`, even when a
registry ignores the requested filter. Descriptors remain untrusted discovery
metadata. Fetch each evidence manifest by its digest, verify its exact bytes and
its subject association, then apply the separate required trust policy.

This adapter requires the native OCI 1.1 referrers API. An unsupported API fails
explicitly; it is not reported as a successful empty evidence list. Legacy
referrers-tag fallback is not implemented, so this is a documented restricted
distribution profile rather than a full OCI legacy-fallback client. The
[OCI specification](https://github.com/opencontainers/distribution-spec/blob/v1.1.1/spec.md#unavailable-referrers-api)
defines that fallback and its concurrent-writer caveat.

Distribution 3.1.1 does not expose that native API and therefore does not support
this adapter's evidence-discovery profile. Package transfer alone can work, but
that must not be mistaken for complete supply-chain registry compatibility. The
real integration fixture uses Zot minimal 2.1.18 for the complete profile.

Redirects are disabled. Upload `Location` and pagination `Link` URLs must remain
within the approved origin/repository and the relevant operation path. Opaque
upload query parameters are preserved. Registries that require object-store
redirects or a separate automatic token origin need a future explicitly approved
integration; this client does not forward credentials to them.

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
limits, separate from the retained-body accounting. Compression, redirects and
automatic retries are disabled. `usage()` reports active operations, retained
package leases, charged raw bytes and whether admission is closed.

## Run the real registry check

Docker must provide Linux containers. Python 3, OpenSSL and the repository's Rust
toolchain are required. Git for Windows' bundled OpenSSL is detected when it is
not on `PATH`. Pull the exact fixture image once:

```console
docker pull ghcr.io/project-zot/zot-minimal-linux-amd64@sha256:f1ffb7a5bbddc0feea83646e29c587ecf39b3193733b447749d4c9ead111a395
python tools/run_oci_registry_tests.py
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
responses and cancellation separately. No benchmark, 100k workload or successful
run report is generated, and these checks do not require native Linux outside
the Docker engine.
