# C dependency selection and security review

Reviewed on **2026-09-19**. The machine-readable source is
[`dependencies.lock.json`](dependencies.lock.json). Download SHA-256 verification
is mandatory, not a best-effort fallback. The supported native build and
compatibility evidence is [recorded separately](EVIDENCE.md).

## Selected graph

| Component | Exact selection | Role |
| --- | --- | --- |
| nghttp2 | 1.70.0, Git `85e300c79fb6dbcfa9c1013215c8710c1c2cd3d2` | Native C HTTP/2 library only |
| sfparse | Git `88a137ab8864556bf6d44cc5639c06f6bafcee57` | Runtime source bundled inside nghttp2 |
| nanopb | 0.4.9.2, Git `160d4f09e5fabb2b66aa2dea32d4f38ace2c4b3f` | Native C protobuf runtime and official C generator |
| protoc | 36.2, Git `2c74169b34066ceb8ddb6b882fcb3fb32d737a55` | Official Linux x86-64 generator executable only |
| Python protobuf | 7.36.2 | Descriptor generation and independent test peer only |
| Python h2 | 4.4.1 | Independent HTTP/2 test peer only |
| Python hpack | 4.2.0 | h2 test dependency only |
| Python hyperframe | 6.1.0 | h2 test dependency only |

There are seven downloaded artifacts and eight source/package components.
`nghttp2.bundled` adds sfparse's commit, upstream URL, purl, role and SHA-256 for
`lib/sfparse.c` and `lib/sfparse.h`; it is not downloaded or linked twice.
The build checks those embedded file hashes. Existing top-level artifact fields
remain `version`, optional `commit`, `role`, `purl`, `url`, `sha256`.

The runtime consists of liblatent (including nanopb), libnghttp2 (including
sfparse), and system libc. nghttp2 application/HTTP3/TLS/mruby dependencies are not
compiled by `--enable-lib-only`. The release's C++23 application requirement is
not a requirement for this C library profile. Matching protoc 36.2/Python protobuf
7.36.2 and nanopb 0.4.9.2 successfully generate/compile the authoritative selected
proto3 messages with the supported C11 compiler. Python wheels are extracted into
the selected build directory, not installed into the host environment.

## Verified source bindings

- The nghttp2 `v1.70.0` annotated tag object is
  `b69da4c2656bb66311c2a84bb2f4a3a1da2da393`; it points to exactly
  `85e300c79fb6dbcfa9c1013215c8710c1c2cd3d2`. GitHub reports its tag signature valid.
  This is a recorded upstream verification result, not a claim that the local
  build independently established a signing-key trust policy.
  [Tag object](https://api.github.com/repos/nghttp2/nghttp2/git/tags/b69da4c2656bb66311c2a84bb2f4a3a1da2da393).
- The release asset `nghttp2-1.70.0.tar.gz` publishes SHA-256
  `aa317e2cf9dca6afa0aed68f8fad6ff303ec6982e25a78c75c0b65e2b9b3ded5`, matching both
  the lock and the downloaded archive. All **53** `lib/**/*.c` / `lib/**/*.h`
  files present in the pinned Git tree matched the archive's Git blob hashes.
  Generated configure/build files are not included in that source-file count.
  [Release](https://github.com/nghttp2/nghttp2/releases/tag/v1.70.0),
  [pinned source tree](https://github.com/nghttp2/nghttp2/tree/85e300c79fb6dbcfa9c1013215c8710c1c2cd3d2/lib).
- Bundled sfparse C/header bytes match the upstream commit exactly: SHA-256
  `90c8f4627a0cf41d421bf2b186d9c9061f5087b23c8015021853788fc529d4c7` and
  `fa99f26ea080137b0f79c3f8799e7513aa1a97fb4c9a4fb1cc42869c17bfac5d` respectively.
  [Pinned sfparse](https://github.com/ngtcp2/sfparse/tree/88a137ab8864556bf6d44cc5639c06f6bafcee57).
- nanopb tag `0.4.9.2` directly names the locked commit. The codeload URL itself
  selects that commit, not a mutable branch.
  [Tag reference](https://api.github.com/repos/nanopb/nanopb/git/ref/tags/0.4.9.2).
- Protobuf annotated tag `v36.2`, object
  `424e1b0a184baa5a3c75061a1febd5f60a0a3707`, resolves to the locked compiler source
  commit. The prebuilt Linux archive is independently hash-pinned.
  [Tag object](https://api.github.com/repos/protocolbuffers/protobuf/git/tags/424e1b0a184baa5a3c75061a1febd5f60a0a3707).

## Independent upstream advisory review

Empty generic ecosystem searches are **not** evidence that native source is
covered. The following published upstream records were reviewed independently
of OSV commit/version queries. This is a dated review of those public records,
not a warranty against undisclosed defects or omitted advisory databases.

| Upstream records | Decision for this pin/profile |
| --- | --- |
| nghttp2 [GHSA-6933-cjhr-5qg6](https://github.com/nghttp2/nghttp2/security/advisories/GHSA-6933-cjhr-5qg6), CVE-2026-27135 | Assertion/state-validation fix is 1.68.1; 1.70.0 is later. Optional extension handlers implicated by the record are not enabled here. |
| nghttp2 [GHSA-x6x3-gv8h-m57q](https://github.com/nghttp2/nghttp2/security/advisories/GHSA-x6x3-gv8h-m57q), CVE-2024-28182 | CONTINUATION fix is 1.61.0; 1.70.0 is later. Client also caps continuations at four. |
| nghttp2 [GHSA-6pcr-v3hg-752p](https://github.com/nghttp2/nghttp2/security/advisories/GHSA-6pcr-v3hg-752p), [GHSA-vx74-f528-fxqg](https://github.com/nghttp2/nghttp2/security/advisories/GHSA-vx74-f528-fxqg), [GHSA-q5wr-xfw9-q7xr](https://github.com/nghttp2/nghttp2/security/advisories/GHSA-q5wr-xfw9-q7xr) | Published memory-leak, Rapid Reset and SETTINGS fixes are 1.55.1, 1.57.0 and 1.41.0; all precede this pin. Our session storage, settings and ACK queues also remain bounded. |
| nanopb [GHSA-p24j-vqcp-x988](https://github.com/nanopb/nanopb/security/advisories/GHSA-p24j-vqcp-x988) | Callback/oneof pointer corruption affects <=0.4.9.1. Pin includes 0.4.9.2 fix; generated oneofs additionally have separate storage (`no_unions`). |
| nanopb [GHSA-9w99-4pfq-6396](https://github.com/nanopb/nanopb/security/advisories/GHSA-9w99-4pfq-6396) | Merely upgrading is insufficient: the new recursion limit is opt-in. This build defines `PB_MESSAGE_NESTING_MAX=16` and the adapter independently enforces depth 16. |
| nanopb [GHSA-xwqq-qxmw-hj5r](https://github.com/nanopb/nanopb/security/advisories/GHSA-xwqq-qxmw-hj5r), [GHSA-7mv5-5mxh-qg88](https://github.com/nanopb/nanopb/security/advisories/GHSA-7mv5-5mxh-qg88), [GHSA-85rr-4rh9-hhwh](https://github.com/nanopb/nanopb/security/advisories/GHSA-85rr-4rh9-hhwh), [GHSA-3p39-mfxg-hrq4](https://github.com/nanopb/nanopb/security/advisories/GHSA-3p39-mfxg-hrq4), [GHSA-gcx3-7m76-287p](https://github.com/nanopb/nanopb/security/advisories/GHSA-gcx3-7m76-287p) | Published fixes predate 0.4.9.2. The client does not enable `PB_ENABLE_MALLOC`; its callback arena remains charged and is cleared on all completion paths. |
| protobuf [GHSA-8qvm-5x2c-j2w7](https://github.com/protocolbuffers/protobuf/security/advisories/GHSA-8qvm-5x2c-j2w7), [GHSA-8gq9-2x98-w8hf](https://github.com/protocolbuffers/protobuf/security/advisories/GHSA-8gq9-2x98-w8hf), [GHSA-h5g9-ghrj-76p5](https://github.com/protocolbuffers/protobuf/security/advisories/GHSA-h5g9-ghrj-76p5) | Selected Python/compiler releases postdate the published Python recursion, C++/Python memory and C++ JSON-parser fixes. Neither Python nor Protobuf C++ is a C-client runtime dependency. |
| h2 [GHSA-6hr6-w5qg-qmwg](https://github.com/python-hyper/h2/security/advisories/GHSA-6hr6-w5qg-qmwg), [GHSA-847f-9342-265h](https://github.com/python-hyper/h2/security/advisories/GHSA-847f-9342-265h) | Test-only 4.4.1 includes the duplicate Host fix and the earlier 4.3.0 CRLF fix. |
| hpack [GHSA-8v8h-hg4w-mvq2](https://github.com/python-hyper/hpack/security/advisories/GHSA-8v8h-hg4w-mvq2) | Test-only 4.2.0 includes bounded integer decoding; <=4.1.0 is affected. |

The public [sfparse](https://github.com/ngtcp2/sfparse/security/advisories) and
[hyperframe](https://github.com/python-hyper/hyperframe/security/advisories)
repository advisory endpoints returned no published records on this date.
That observation does not guarantee coverage or safety. Published Protobuf Java,
PHP, Kotlin and JRuby advisories were also inspected but do not describe packages
used by this C build. Prebuilt protoc's entire embedded binary dependency closure
is **not** independently inventoried by this C source graph.

Retain the upstream notices when distributing the selected libraries, including
nghttp2 [COPYING](https://github.com/nghttp2/nghttp2/blob/85e300c79fb6dbcfa9c1013215c8710c1c2cd3d2/COPYING),
nanopb [LICENSE.txt](https://github.com/nanopb/nanopb/blob/160d4f09e5fabb2b66aa2dea32d4f38ace2c4b3f/LICENSE.txt),
sfparse [COPYING](https://github.com/ngtcp2/sfparse/blob/88a137ab8864556bf6d44cc5639c06f6bafcee57/COPYING),
and the compiler/Python distributions' notices. The build preserves the original
source and wheel license files; it does not relicense upstream code.

## Fresh query and parent inventory interface

```sh
python3 sdk/c/tools/audit_dependencies.py \
  --graph target/c-sdk/dependency-graph.cdx.json \
  --report target/c-sdk/dependency-audit.json
```

The last recorded query at **2026-09-19T15:58:20Z** submitted nine queries:
nghttp2/nanopb/protoc/sfparse Git commits, plus exact PyPI versions for
nanopb/protobuf/h2/hpack/hyperframe. All returned empty findings, with no pagination
token. The lock SHA-256 was
`0a8dd5f411e104d4171c357cfb2f98e78f99436ef94457af70a0f1a79fb6256d`.
No open returned advisory required a further version change. Network, incomplete
result, pagination or finding errors fail the audit; they are not reported as a
clean observation. [OSV query API](https://google.github.io/osv.dev/api/#tag/api/operation/OSV_QueryAffectedBatch).

The graph is **CycloneDX 1.6 JSON**, with stable `latent-c:NAME` component refs,
purls, artifact hashes, source commits and `latent:dependency-role` properties.
Edges include nghttp2 -> bundled sfparse, h2 -> hpack/hyperframe, and nanopb ->
Python protobuf for generation. The nanopb edge does not make Python a runtime
requirement. Bundled file hashes are properties named
`latent:bundled-file-sha256:PATH`. The root lists the seven direct artifacts; its
dependency closure contains eight components. The audit JSON retains exact query
objects, responses, UTC timestamp, lock digest and coverage limitation.

This is C-owned data for the parent security inventory, not a replacement for its
policy or tooling. Native Git indexing, package aliases, current public advisory
availability, system compiler/libc/container packages and prebuilt tool binary
closure each have separate coverage limits. Empty responses never mean a generic
native ecosystem name matched or that the complete deployment has no known risk.
