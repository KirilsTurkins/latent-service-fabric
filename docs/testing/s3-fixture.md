# Source-built S3 conformance fixture

The S3 wire-profile tests use one disposable MinIO server, not a deployed storage
service or a new supported production distribution. The earlier pinned public
image stopped allowing anonymous acquisition. The maintainer approved replacing
that fixture; its old successful and failed attempts remain separate evidence.

## Pinned inputs

- Official MinIO [security release](https://github.com/minio/minio/releases/tag/RELEASE.2025-10-15T17-29-55Z):
  `RELEASE.2025-10-15T17-29-55Z`, commit
  `9e49d5e7a648f00e26f2246f4dc28e6b07f8c84a`.
- Source archive: 24,232,282 bytes, SHA-256
  `45521908307306e925c98d629e1c17d78c8b72b6ee242b1bfb1409f7d8ee5841`.
- Linux amd64 Go 1.27.1 Bookworm compiler:
  `docker.io/library/golang@sha256:966278043a40889499db9b0cd196fc789c37c385d41bd9a10cb1e7764af60cdc`.
- The upstream `go.mod` and `go.sum` hashes are independently fixed in
  `tools/build_s3_fixture.py`. Module resolution uses the public Go proxy and
  checksum service, with no direct fallback, module updates or toolchain download.

The upstream repository is archived and the release commit is unsigned. The
official tag mapping and measured archive checksum bind the selected source;
they are not a signature verification or a claim of comprehensive security
qualification. The release addresses the publisher's
[CVE-2025-62506 advisory](https://github.com/minio/minio/security/advisories/GHSA-jjjj-jwhf-8rgr).
No general S3 compatibility or production suitability follows from this fixture.

## Build and reuse

Prerequisites are Linux amd64, Python 3.11 or newer, a Linux Docker daemon and
public HTTPS access to GitHub, the official Go image and Go module services.
Use a fresh output directory so previous failures cannot be overwritten:

```bash
python3 tools/build_s3_fixture.py --output target/s3-fixture-attempt
python3 tools/run_s3_blob_tests.py --image-receipt target/s3-fixture-attempt/fixture.json
```

The S3 runner requires an explicit image receipt. Prepare it separately so the
builder keeps its own cancellation/cleanup owner and retained evidence directory.
A malformed, stale or missing receipt fails closed; it never triggers a
replacement pull or a rebuild. CI prepares the fixture before its
co-located provider/renderer lanes and passes the same receipt to the existing
positive S3 test and wrong-harness negative control.

The source download has an original 125-second process budget and exact byte
limit. Before extraction, the helper verifies the archive hash and rejects
links, special files, aliases, traversal and excessive entries/expanded bytes.
The compiler image is pulled by its platform-specific digest. An explicitly
owned compiler container has two CPUs, 6 GiB RAM/no extra swap, 256 PIDs and
bounded source (512 MiB), module (2 GiB), build-cache (1 GiB) and temporary
(2 GiB) filesystems. Final filesystem usage is retained in the build diagnostic.
The complete build owner has
1,500 seconds including cleanup. These are preparation limits, not changes to
activation deadlines or provider/renderer lane budgets.

The helper builds only the server with `CGO_ENABLED=0`, `GOTOOLCHAIN=local`,
`-mod=readonly`, `-trimpath`, `-buildvcs=false` and fixed release metadata.
It verifies the module cache, forbids network module resolution during the
compile command, and checks that the pinned module files remain unchanged.
The selected source, Go modules and compiler may still use network during
preparation; this is not a whole-build hermeticity or bit-reproducibility claim.

A curated root filesystem contains the static amd64 binary, upstream license
and credits, and the compiler image's CA bundle. There is no inherited MinIO
image, package installer, shell or client in the resulting runtime image.
`docker image import` creates a local immutable image ID, never a published tag.
The receipt binds source, compiler, helper recipe, binary, rootfs and image
identities. The image's actual rootfs digest and labels are checked; the server
is launched with `--pull=never`, and its actual container image ID is checked.

## Ownership and evidence

The compiler container's random owner label and immutable ID are verified before
removal, then absence is confirmed. A usable success receipt is written only
after that cleanup succeeds. A failed download/build/import retains its attempt
files and diagnostic; it cannot produce an accepted receipt. A partial image
import with a lost reply may leave an unqualified static image labelled with the
diagnostic's run ID. It is not treated as absent or retried automatically.

Source archives, binary, notices, build information and the image receipt remain
explicit build outputs. The local image is deliberately retained for reuse, not
silently deleted from a shared daemon. CI uploads the build outputs and failure
diagnostics with finite artifact retention. No registry publication is performed.

The real server retains the existing TLS setup, one CPU, 512 MiB memory, 128 PID,
read-only root, loopback endpoint, finite data/tmp/log storage and owner-checked
container cleanup. The two real S3 tests, 300-second harness limit, wrong-harness
negative control and all provider assertions are unchanged. A source-build pass
alone does not qualify them or replace complete CI.
