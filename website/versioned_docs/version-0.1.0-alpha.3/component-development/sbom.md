# Package SBOMs and bounded content policy

`latent-packaging` generates and checks a closed CycloneDX JSON 1.6 inventory,
embeds it in a package, and checks detached SBOM associations and content policy.
The maintained echo observer exports normalized inventory from the build records
it already captures. Publisher authentication and the final catalog admission
decision remain separate from inventory validation.

`decode_sbom_inventory` validates the closed
[normalized input](../../schemas/package-sbom-inputs.schema.json).
`build_package_with_sbom` generates and adds the reserved asset before normal
package assembly. `generate_cyclonedx_sbom` and `inspect_cyclonedx_sbom` expose the
standalone bounded encoder and inspector, preserving an exact-byte digest.

After producing the [observed echo inputs](../reference/build-provenance.md#observe-an-actual-build),
use a fresh output directory:

```sh
cargo run -p latent-packaging --example package --locked -- build-with-sbom target/capsules/echo-provenance/package-source.json target/capsules/echo-provenance/sbom-inputs.json target/capsules/echo-provenance target/package-echo-sbom
cargo run -p latent-packaging --example package --locked -- inspect target/package-echo-sbom
```

The example reads the normalized inventory separately with a 1 MiB cap. The
observer's `sbom-inputs.json` is an unsigned handoff beside its recipe, not an
extra package layer. Inspection reports the checked SBOM digest and entry count.

## Package identity and exact bytes

The reserved asset `package/sbom.cdx.json` uses media type
`application/vnd.cyclonedx+json`. Generate it before package assembly. Its root
records logical package name, version and kind; it never contains the final
`PackageDigest`. The manifest then binds the exact SBOM bytes through the asset's
SHA-256 and size. This avoids a circular hash dependency.

The inventory excludes itself and `package/build-inputs.json`, the generated
packaging receipt. It records limited input/output coverage rather than claiming
a complete dependency closure. Component, WIT and supported output asset rows
must match independently inspected package content. Metadata canonicalized by
packaging is not mislabeled as an unchanged output file.

Inspection preserves received bytes. A malformed file at the reserved path fails
package inspection even when policy permits packages without an SBOM. A checked
summary has private construction and bounded retained data; deserializing public
inventory input does not create a trusted result.

After assembly, the same SBOM bytes can be attached as
`application/vnd.latent.sbom.v1` evidence. The existing OCI evidence envelope has
exact empty configuration `{}`, one
`application/vnd.latent.sbom.payload.v1+json` layer, and an outer subject containing
the final package media type, digest and size. The payload must equal the unique
checked embedded SBOM in digest, length and bytes.

`attach_package_sbom` borrows the checked bundle's exact payload;
`inspect_sbom_association` verifies supplied envelope/config/payload bytes.
Their returned identities carry no publisher authorization.

Matching evidence establishes association. Authenticating a publisher proof for
the exact package also binds the embedded inventory; changing its bytes changes
package identity. Referrer presence by itself authenticates no author and cannot
turn declared dependencies into independently proven program behavior.

## Observed inputs and attribution

The [build observer](../reference/build-provenance.md) emits `sbom-inputs.json`
while its captured source, selected dependency manifests and compiler records are
available. Rust performs the CycloneDX encoding. The observer does not run another
compiler or a dependency-resolution command merely to collect inventory.

Cargo compiler-artifact records identify units observed during the maintained
build, including cached units. Host build dependencies, procedural macros and
build scripts remain distinct from guest target dependencies. A package used in
multiple contexts may have multiple role-specific rows. The inventory also
records pinned WIT inputs, selected tools and package assets.

Source and license information remains explicit declared attribution or
unavailable. Captured registry archive checksums identify lockfile-declared
archives; they do not hash unpacked source, a linked binary or an independently
verified cache. Manifest metadata read from an approved cache is identified as
such. Raw compiler messages, private host paths and credentials are not exported.

Only independently known associations are checked. Opaque Wasm does not expose a
complete linked dependency inventory, and compiler output does not prove which
instructions or licensed material survived linking. Browser/SSR packages can
inventory their assets while application dependencies and licenses remain
unavailable when no authoritative inputs were supplied. No dependency edges are
invented from flat build-unit records.

Normalized inventory identity and producer helper identities are included in the
build observation. That handoff is unsigned until an independently approved
builder signs the exact final package and observation. Package publisher and
builder roles remain separately approved.

## Supported CycloneDX profile

The profile closes structural fields, rejects unknown properties, and makes
source/license status consistent with the corresponding values. Output roles,
hash meanings and source identities are constrained rather than accepted as
arbitrary property bags. All hash records use SHA-256 and exactly 64 lowercase
hexadecimal characters. Generation sorts supported collections for deterministic
bytes; inspection does not rewrite an external document.

| Inventory role | CycloneDX component type |
| --- | --- |
| `guest-dependency`, `build-dependency`, `proc-macro`, `build-script`, `wit-package` | `library` |
| `build-tool`, `component`, `renderer` | `application` |
| `asset` | `file` |

The root uses `bom-ref=urn:lsf:package:input`; fixed metadata includes
`lsf:profile=lsf-cyclonedx-embedded-1` and
`lsf:subject-kind=package-content`. Package kind is `capsule`, `browser-assets` or
`ssr-package`. Dependency completeness is explicitly
`observed-units-incomplete` or `declared-inputs-incomplete`; neither means a
complete linked dependency graph.

Known SPDX declarations use the expression choice, including simple identifiers,
with `lsf:license-status=declared`. A pinned parser validates syntax and identifiers
after bounded lexical work. Invalid expressions are not silently repaired or
converted to named licenses. Named licenses and standalone license-ID objects
are outside this expression-only input profile. The profile does not interpret
declarations as a legal compatibility decision.

The upstream [CycloneDX JSON 1.6 schema](https://raw.githubusercontent.com/CycloneDX/specification/55343ba19dee1785acf1ce9191540d5fd7b590db/schema/bom-1.6.schema.json)
is pinned with its transitive schema references and license under
[the pinned offline data](../../tools/data/cyclonedx-1.6/README.md).
It accepts string expressions without validating SPDX grammar, so schema
validation alone is insufficient. The supported parser vocabulary is pinned by
[`spdx` 0.13.5](https://docs.rs/crate/spdx/0.13.5/source/Cargo.toml.orig); optional
license-text detection, network lookup and advisory feeds are not enabled.

The observer uses a narrower subset of known nondeprecated SPDX 3.23 license
identifiers with bounded uppercase AND/OR and grouping. Unsupported declarations
remain unavailable in that producer output. Its derived identifier list excludes
exceptions; an exception cannot masquerade as a standalone license. Rust still
validates every supplied expression independently, including its supported WITH
exceptions, using the pinned parser. This distinction does not upgrade unavailable
metadata or claim that the two accepted vocabularies are identical.

## Policy and admission boundary

Content policy explicitly selects optional or required embedded and detached
presence, plus source/license requirements for fixed roles. Its canonical digest
binds every choice. Supplied malformed, duplicated, conflicting or mismatched
evidence fails even when its presence is optional. Policy evaluation does not
grant publisher, builder, tenant or execution authority.

The [admission owner](../reference/package-admission.md) combines these results
with current package publisher proofs, required builder provenance and its own
current policy generation at final publication. SBOM policy has no independent trust store,
clock owner, hidden network discovery or authority-refresh mechanism.

`SbomPolicy::new` and `from_json` validate the explicit
[policy shape](../../schemas/package-sbom-policy.schema.json). Use its
`canonical_bytes()` and `digest()` for policy identity, rather than hashing an
unsorted input document. `evaluate_sboms` returns private package, policy,
inventory and referrer identities after checking all supplied associations.

## Validation and limits

Document bytes, JSON depth/nodes, entries, properties, strings and license tokens
are bounded before typed retention or sorting. Defaults are hard ceilings that
callers may lower. Evidence count and aggregate bytes are checked before inspecting
supplied associations. Limits bound supported input, work and retained summaries;
they are not exact process-RSS guarantees.

| SBOM resource | Default / hard ceiling |
| --- | --- |
| Raw normalized inventory or CycloneDX document | 1 MiB |
| Entries / JSON depth / JSON nodes | 4096 / 12 / 131,072 |
| Generic decoded strings / object members / property array | 4096 bytes / 24 / 16 |
| Package name and version / entry name and version | 128 each / 256 and 128 bytes |
| Source / SPDX expression / SPDX tokens and grouping | 512 / 1024 bytes / 128 and 16 |
| Output logical path / one recorded content size | 240 bytes / 256 MiB |
| Manifest size | Positive, at most 4 MiB |

Strings use printable ASCII. Output paths additionally follow the package's
portable segment rules. Document, node and field limits apply together, so a
combination of individually valid entries may exceed the aggregate budget.

Policy JSON is limited to 4096 bytes, depth 4 and 64 nodes; its two role lists
each contain at most nine unique supported roles. Evidence permits at most
eight supplied referrers, 4096 bytes per manifest, 1 MiB per payload and
`8 * (1 MiB + 4096 + 2)` total supplied bytes. The enclosing package and SBOM
parser limits still apply independently.

Tests validate generated documents against both the local LSF schema and the
offline pinned CycloneDX schema. Rust checks cross-field identity, SPDX syntax,
paths, duplicate/conflicting declarations, exact embedded/detached association,
policy and reduced resource ceilings. The existing small observed build and
disposable authenticated registry exercise the real path without a load campaign.

Run `cargo test -p latent-packaging --locked` and
`python -m unittest tools.tests.test_sbom_schemas tools.tests.test_sbom_policy_schema tools.tests.test_sbom_upstream`.

See [ADR-0024](../../adr/0024-bind-sbom-inventory-through-package-content.md),
[packaging](packaging.md), [publisher trust](../reference/publisher-trust.md) and
[OCI transfers](../reference/oci-registry.md).
