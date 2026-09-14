# S3 immutable blobs

`latent-blobs::s3` implements `s3-versioned-immutable-blobs-v1` for
[#214](https://github.com/KirilsTurkins/latent-service-fabric/issues/214). It uses
the same `latent:blob/blob@0.2.0` guest interface and owned chunks as
[local blobs](local-blobs.md). Installation is an explicit trusted embedding
operation. Standalone provider configuration and operator commands remain
[#226](https://github.com/KirilsTurkins/latent-service-fabric/issues/226);
declaring an import does not enable S3 access.

## Supported transport and credentials

The initial profile requires one HTTPS origin, explicitly approved static peer
addresses, one region, one DNS-style bucket name without dots, and a fixed
relative ASCII prefix ending in `/`. The bucket must have versioning enabled.
LSF rejects missing or `null` version receipts. TLS verifies both the approved
peer and the configured hostname, using explicit DER roots and/or explicitly
enabled public roots. This profile uses path-style S3 requests and HTTP/1.1.

Guests cannot select an endpoint, bucket, prefix, remote object key or signing
identity. Each configured tenant has a separate opaque
[protected credential binding](local-secrets.md). One reference contains the
access key, secret key and optional session token, separated by LF, with no
trailing LF. The entire tuple rotates atomically. The adapter resolves its current
value before each signed request and checks the actual tenant, provider ID and
origin. It has no guest secret-read authority. Secret material is excluded from
public configuration digests, inventory records, debug output and snapshots.

The provider implements AWS Signature Version 4 for fully hashed payloads. It
does not use an ambient SDK credential chain, DNS resolver, proxy, redirect,
automatic token acquisition, transparent retry or response decompression.
Preissued temporary session tokens are supported; automatic refresh is not.
The wire profile is tested with
`quay.io/minio/minio@sha256:a1a8bd4ac40ad7881a245bab97323e18f971e4d4cba2c2007ec1bedd21cbaba2`
(MinIO `RELEASE.2025-09-07T16-13-09Z`, Linux amd64). This is a tested S3 subset,
not a compatibility claim for every server, vendor or AWS deployment policy.

## Writes, immutable references and reads

`create` reserves the finite staging exposure and prepaid 64 KiB pages before
allocating them. `write` accepts sequential offsets and bounded chunks. The
provider hashes both the complete object and each 5 MiB part incrementally.
An expected size must match exactly at `seal`; an omitted size reserves the
configured maximum. No remote upload starts before sealing.

Before a remote mutation, the provider durably records the exact tenant,
namespace, SHA-256, size, media type, part hashes and unique object key. Nonempty
objects use CreateMultipartUpload, sequential UploadPart requests and a
conditional CompleteMultipartUpload. All parts except the last are 5 MiB.
Empty objects use a conditional zero-byte PutObject. Completion checks the XML
body as well as the HTTP status: an HTTP 200 containing an S3 `Error` is not a
successful seal. A successful receipt pins a non-null object version.

The guest reference remains a value containing digest, size and media type.
The original session supplies tenant authority, and the installed provider
supplies the namespace. Private durable receipts bind that tuple to the exact
remote key and version. Identical data under another tenant has an independent
receipt. A sealed duplicate can reuse its existing receipt; an unresolved
duplicate fails without starting another upload.

Reads address the retained version, so replacing the current object does not
silently change a reference. Each requested range fetches its intersecting
whole parts and verifies the retained part SHA-256, exact Content-Range, byte
count and version before exposing any guest chunk. ETag is never treated as the
content digest. A corrupt response produces no retained guest result.

This conservative initial read profile can fetch up to 10 MiB for a range of at
most 64 KiB crossing a part boundary. It favors independent verification without
retaining a downloaded whole object. No low-latency or low-egress-cost claim is
made for small random reads. HTTP/1.1 connections close after each response;
their actual socket/TLS driver remains charged until destruction.

## Ownership and finite limits

| Resource | Default | Absolute ceiling |
| --- | ---: | ---: |
| Object bytes | 8 MiB | 32 MiB |
| Concurrent staged objects | 2 | 8 |
| Total reserved staging | 16 MiB | 32 MiB |
| Durable receipts, including unresolved uploads | 64 | 128 |
| Sealed and unresolved remote byte reservations | 256 MiB | 1 GiB |
| Open reader handles | 64 | 256 |
| Guest write/read chunk | 64 KiB | 64 KiB |
| S3 XML body | 32 KiB | 32 KiB |
| XML nesting/events/fields | 8 / 2,048 / 256 | same |
| Reconciliation abort/list attempts per call | explicit 1–4 | 4 |
| Maintenance deadline | explicit | 2 minutes |

These bounds intersect with the independent broker, activation, I/O and
[provider-pool limits](provider-pools.md). Write arguments also include their
typed framing bytes; those must fit the broker input ceiling. Seal prepays the
actual maximum outbound request count: one for an empty object, otherwise
create + number of parts + completion. A read prepays the number of intersecting
parts. Blob byte budgets remain cumulative across calls.

Staging pages, TLS/parser workspace, credentials and inventory metadata share
the configured provider metadata budget. Inventory startup prepays 64 KiB for
each allowed record plus one owner allowance. The default S3 limits therefore
need an explicitly enlarged pool to admit maximum-size stages; the standalone
pool's 8 MiB default is not an implicit extra S3 allowance. The conformance
embedding uses a 32 MiB pool and an eight-record inventory. Insufficient capacity
rejects before allocation. No dormant deployment acquires a provider, socket,
worker, timer or buffer of its own.

`S3Snapshot` reports counts, reserved remote/staging bytes, active upload owners,
reader handles, inventory file allowance and a poisoned-state flag. The finite
`pending()` view exposes opaque inventory IDs and counts, not object URLs,
payloads, upload IDs or credentials. Original capability calls use the existing
audit owner, including `BlobSealed` or uncertainty outcomes. Pool and I/O
snapshots report their physical work independently.

## Restart and explicit recovery

The Linux inventory uses private descriptor-relative, no-follow files, a retained
exclusive lock, bounded sidecars and file/directory durability fences. Unknown
entries, unsafe permissions and substituted files fail closed. A valid pending
transition is recovered; a torn pending write cannot authorize the next remote
mutation. The prior durable state is retained. This inventory contains no
staged payload replay log or guest application state.

Dropping a waiter closes owned network work but cannot prove a remote part
stopped. Durable uncertainty remains charged after cancellation, process restart,
an unavailable cleanup service or exhausted cleanup attempts. A known initial
authentication/not-found rejection can retire its empty intent; it does not
strand a nonexistent upload. Later failures with retained parts still require
cleanup.

An authenticated operator can call `reconcile` for an exact pending inventory ID:

- A lost creation response requires positive, bounded discovery of its exact
  unique key before aborting. One empty listing is not a quiescence proof.
- A known upload uses bounded AbortMultipartUpload and ListParts verification.
  Ordinary `Observe` recovery cannot refund a part whose response was lost,
  even when the upload currently appears absent.
- `AfterOperatorConfirmedQuiescence` is an explicit operator assertion, based on
  the selected server's administration, that remote part work has ended. It still
  requires successful abort/list verification. A timeout or empty list alone
  does not justify this mode.
- For uncertain completion, recovery can inspect an existing exact version and
  independently verify every retained part and the complete SHA before recording
  a sealed receipt. It never repeats Complete or performs a full re-upload.

Recovery uses a finite node maintenance permit and the same connection/worker
pools. It cannot manufacture a guest session. Closed sockets, completed workers,
and durable remote cleanup are distinct observations. Shutdown may finish local
work while unresolved remote reservations remain in the durable inventory.
Sealed objects remain retained; this initial guest profile exposes no deletion
operation or automatic remote object garbage collector.

These are immediate capability operations under
[ADR-0025](../../adr/0025-separate-immediate-capability-operations-from-transactional-effect-intents.md).
A receipt does not commit application state, undo a possible remote effect,
provide an outbox or promise exactly-once mutation.

## Validation

```bash
cargo test --locked -p latent-blobs --lib
cargo test --locked -p latent-wasmtime --test s3_blobs
docker pull quay.io/minio/minio@sha256:a1a8bd4ac40ad7881a245bab97323e18f971e4d4cba2c2007ec1bedd21cbaba2
python3 tools/run_s3_blob_tests.py
```

The normal suite covers signing vectors, finite XML, tenant receipts, unsafe
files, torn transitions, cancellation, late parts, failed cleanup, corrupt range
responses and no replay after uncertain completion. The owned MinIO runner
executes the existing actual blob guest, empty objects, multipart writes,
cross-part ranges, wrong credentials, verified restart recovery and reads after
replacing the current version. It removes its server, payloads and temporary
inventory and caps container memory, storage, PIDs and logs. CI reuses its
already-built workspace test harness. These are bounded conformance tests,
not a load benchmark or a general S3 certification.

Protocol references:
[SigV4](https://docs.aws.amazon.com/AmazonS3/latest/developerguide/sig-v4-header-based-auth.html),
[completion errors](https://docs.aws.amazon.com/AmazonS3/latest/API/API_CompleteMultipartUpload.html),
[abort and in-flight parts](https://docs.aws.amazon.com/AmazonS3/latest/API/API_AbortMultipartUpload.html),
[multipart checksums](https://docs.aws.amazon.com/AmazonS3/latest/userguide/checking-object-integrity-upload.html).
