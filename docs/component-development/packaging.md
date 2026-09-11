# Deterministic package build and inspection

`latent-packaging` implements the bounded build/inspect workflow from
[#141](https://github.com/KirilsTurkins/latent-service-fabric/issues/141), using
the [Phase 2 artifact format](../protocol/package-format.md). It packages supplied
bytes without compiling a component or invoking a guest. The separate
[registry adapter](../reference/oci-registry.md) transfers its bytes. Publisher
verification and catalog admission remain subsequent Phase 2 tickets.

## Build a small package

From a checkout with the pinned Rust toolchain:

```sh
cargo run -p latent-packaging --example package --locked -- build examples/package-inputs/browser/package-source.json examples/package-inputs/browser target/package-browser
cargo run -p latent-packaging --example package --locked -- inspect target/package-browser
```

Use a new output directory on every export. The writer refuses to overwrite an
existing directory. The SSR fixture uses the same commands with
`examples/package-inputs/ssr` and `target/package-ssr`. Neither command starts a
browser, renderer, server or service instance. This small example drives the
public Rust API; the integrated operator CLI is tracked by
[#156](https://github.com/KirilsTurkins/latent-service-fabric/issues/156).

The [source recipe schema](../../schemas/package-source.schema.json) requires
`formatVersion: 1`, `kind`, `name`, `version`, `entrypoint`, `annotations` and
`layers`. Each selected file requires a logical `path`, relative `source`,
`role` and `mediaType`. The separate input root is caller-approved filesystem
authority. No absolute path, glob, recursive input discovery or archive
extraction is supported. All descendant path segments reject symlinks, and
selected inputs must be regular files. Traversal, case collisions and
file/directory prefix collisions are rejected.

Input files should remain unchanged during a build. The reader checks file
length and modification state around bounded reads, and the package identifies
the exact captured bytes. This is not a filesystem-wide atomic snapshot.

## Capsule inputs and validation

A capsule requires one component, capsule manifest, typed-contract document and
WIT lock, plus the exact UTF-8 WIT sources referenced by that lock. WIT sources
are `asset` layers with `text/plain` media type. See the
[lock graph contract](../protocol/package-format.md#wit-source-lock-graph).

The supplied capsule manifest must contain the actual component SHA-256, pinned
world and implementation version. The implementation version must equal the
package version; the package name remains distinct from the scoped capsule
resource name. The original lock must name the actual supplied contracts bytes.
When canonicalizing contracts, the builder updates that lock association to
the canonical output hash. Wrong original associations are rejected first.

Validation covers:

- Complete binary validation, including function bodies in unused nested modules.
- Exact package/source/dependency identities and a resolved pinned WIT world.
- Actual component import/export sets and complete supported parameter/result,
  record, variant, enum, list, tuple, option, alias and result structures.
- Repository-authoritative context, log and clock host interfaces. Unknown host
  imports, unsupported world items, asynchronous/resource/future/stream/flags
  surfaces and exports without callable functions are rejected.
- Existing manifest execution constraints and typed descriptor consistency.

Compilers can omit unused host interfaces, functions and types. Every retained
import must match the declared source exactly; the full source host interface
must match the repository definition. Exported interfaces remain exact. The
checked summary reports the declared source surface, including imports removed
by the compiler.

Each exported interface requires exactly one matching contract descriptor and
one interface descriptor. Functions are synchronous freestanding functions with
`id == name`; an unnamed WIT result projects to metadata name `result`.
Dependencies are sorted direct interface dependencies, not the world's host
imports. Records/variants retain their named legacy projection, enums use the
legacy named variant form, and byte lists can use `Bytes` or `List(U8)`.

Interface/contract hashes preserve the existing algorithm: compact UTF-8 JSON
with recursively sorted object keys, array order preserved, and only the
current object's `digest` omitted. Contract hashes include interface digests.
Supplied stale hashes are rejected. Documentation and attributes are preserved
and remain digest-bound. WIT supplies the full named type definitions missing
from those legacy descriptors.

This validates structural association and the supported packaging profile. It
does not prove guest behavior, publisher trust, current node target suitability
or safe release-to-release promotion. Those later checks must use the retained
exact package/WIT bytes and current operator policy.

## Determinism and observed input identities

`build_package(PackageInput, PackagingLimits)` sorts logical paths, canonicalizes
metadata and emits the versioned package JSON profile. It adds the reserved
asset `package/build-inputs.json`; callers cannot supply that logical path.

The [receipt schema](../../schemas/package-build-inputs.schema.json) records
format version 1, operation `package-supplied-artifacts`,
packager name/version, and each original logical input's role, digest and size
together with its output digest and size. The receipt is bound by the package
like every other layer, and does not include its own or the package's digest.
This avoids a content-hash cycle. Inspection checks all output associations.

Input hashes describe bytes observed by a local packaging call. In a received
receipt, they are publisher assertions until authenticated provenance verifies
them. The receipt does not invent the component's compiler, source revision,
license inventory, cleanliness, timestamps or reproducible compilation status.

Identical supplied bytes, logical paths, recipe metadata and packager version
produce identical package bytes. Physical roots and file-selection order do
not affect identity. Different raw JSON whitespace can change recorded input
hashes, even if canonical metadata outputs match. Detached signatures and
attestations are separate from this deterministic payload.

An external package can be inspected without this packager-specific receipt.
Receipt presence never substitutes for verified build provenance or admission.

## Ownership and bounds

The API returns `PackageBundle`, which privately owns exact manifest/config/blob
bytes and a small checked capsule summary. `inspect_bundle` verifies supplied
buffers; `read_package_input` reads a typed recipe; `decode_package_source`
decodes a bounded recipe; `read_package_directory` verifies an exported package.
Bundles expose borrowed read-only accessors and carry no trust/admission token.

Package-format limits include 256 KiB documents, 256 total layers, 64 MiB per
layer and 256 MiB aggregate content. Builds reserve one layer for their receipt,
so recipes have at most 255 inputs. Capsule/contract/lock documents also use the
package document ceiling. Filesystem inventories are limited to the files and
directories implied by those validated paths; extra entries are rejected.

Semantic defaults are hard ceilings that callers may lower:

| Resource | Ceiling |
| --- | --- |
| Component bytes / component nesting | 64 MiB / 16 |
| Binary sections / component items | 8,192 / 16,384 |
| Core functions / declared locals / operators | 65,536 / 1,048,576 / 2,000,000 |
| Examined type nodes / type depth / members per type | 65,536 / 64 / 1,024 |
| Names / parameters per function | 512 bytes / 256 |
| WIT packages / individual source / aggregate source | 256 / 256 KiB / 4 MiB |
| Aggregate WIT tokens | 262,144 |
| Imports / exports / functions | 64 / 256 / 4,096 |
| Retained checked summary | 1 MiB |

Byte, lexical, nesting, vector and transitive type-graph checks precede the
recursive validator and component decoder. Expanded-work accounting is
conservative: shared types and aliases can consume the budget more than once,
so a structurally valid large graph can exceed the supported profile. The
limits bound input/work and retained summaries, not exact RSS. Packaging is a
synchronous caller-owned operation with no hidden queue or worker pool. The
output parent must remain operator-controlled during export. A failed export
is cleaned up where possible; interruption before the final manifest commit
leaves an unreadable partial directory. Client exports do not claim the node
catalog's crash-durability guarantees or change catalog visibility.

## Validation

```sh
cargo test -p latent-packaging --locked
python -m unittest discover -s tools/tests -p test_package_source_schema.py
python -m unittest discover -s tools/tests -p test_package_receipt_schema.py
```

Tests construct small real Component Model binaries in memory using the pinned
encoder, with nested types and a clock import. They check build/inspect identity,
input receipts, metadata/WIT/binary mismatches, unused invalid bodies, parser
limits, path handling, directory inventories and failed/partial output. Symlink
tests run on Linux CI. No guest invocation, large compiled fixtures or load
campaign is needed. The original Phase 0 echo builder and evidence are unchanged.
After the existing echo build, CI also runs `python tools/validate_package_smoke.py`
to package and inspect that real Rust component and the browser/SSR fixtures
twice. Temporary outputs are removed when the smoke check exits.

See [ADR-0020](../../adr/0020-validate-supplied-components-without-executing-guests.md)
for dependency and compatibility decisions.
