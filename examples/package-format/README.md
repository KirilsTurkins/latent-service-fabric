# Package format golden fixtures

These small fixtures exercise the [Phase 2 package format](../../docs/protocol/package-format.md)
and its [schemas](../../schemas/README.md). They cover capsule, browser asset,
SSR and detached signature/provenance/SBOM envelope shapes. They are format
examples, not published or trusted releases.

The capsule's `component.fixture` contains deliberately opaque, non-executable
bytes. Its capsule-manifest and typed-contract payloads are placeholders. The
WIT lock pins an exact source file and contracts payload, but this does not
prove agreement with a compiled component. The JavaScript renderer is an opaque
format example without an SSR runtime integration claim. Evidence payloads are
unsigned placeholders; their MIME types and subject associations confer no
authenticity. The completed Phase 2 [packaging](../../docs/component-development/packaging.md),
[compatibility](../../docs/reference/release-compatibility.md) and
[admission](../../docs/reference/package-admission.md) implementations use their
own executable and signed fixtures; these golden format bytes do not become
executable or trusted because those features are delivered.

`golden.json` is a checked-in known-answer index. Paths in it are relative to this
directory. Each `packages` entry records its `kind`, `config` and `manifest`
files, plus `blobs` mapping logical package paths to physical fixture files.
Every file record contains the exact byte `size` and lowercase SHA-256 `digest`.
Each `evidence` entry records its manifest, payload and package `subjectKind`;
`emptyConfig` records the shared two-byte `{}` OCI configuration. These records
are a test index, not another package wire format.

Configuration, OCI manifest and WIT lock files use compact UTF-8 JSON with no
trailing newline. Their member order follows the documented codec, annotation
keys are sorted, and layers are sorted by logical path. One annotation includes
non-ASCII text and JSON quotes so byte hashes and escaping are exercised.
Payload bytes retain their literal newlines. The package digest identifies the
exact manifest bytes; reformatting any hashed JSON changes its identity.

The Python tests independently check the schema shapes, canonical known answers,
every byte hash and length, the configuration/layer graph, WIT source graph and
detached subjects. Negative cases mutate copies in memory, so no malformed JSON
needs to be retained in the repository. Run them from the repository root:

```sh
python -m unittest discover -s tools/tests -p test_package_format.py
```

The tests require the repository's development Python dependencies. Rust codec
tests consume the same fixtures to check interoperability. This corpus is under
20 KiB before documentation and needs no generated load reports or benchmark
artifacts.
