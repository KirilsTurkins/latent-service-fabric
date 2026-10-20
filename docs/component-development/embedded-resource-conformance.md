# Embedded resource breadth

This finite candidate fills the remaining byte/empty-data observations in the
maintained Go, Rust and TypeScript resource paths. It uses two ordinary local
packages, absent from the catalogue, captured by normal native dependency
authoring and exact lock review. Their original source trees are removed before
the component compiler runs. No application resource callback or filesystem provider is
installed.

| Language | Actual standard operations in the outside dependency | New signed plan |
| --- | --- | --- |
| Go | `embed.FS.ReadFile`/`Open`, `io.ReadFull`, `errors.Is(err, fs.ErrNotExist)`; exact UTF8+NUL, binary, empty text/binary and EOF; independent stream positions and `ReadFile` copies | Six data calls, trap, fresh binary recovery |
| Rust | `include_str!`/`include_bytes!`, borrowed static slices and independent `std::io::Cursor` positions; both empty text and empty bytes | Four data calls, trap, fresh binary recovery |
| TypeScript | Static `.txt`/`.bin` imports, empty string/`Uint8Array`, exact UTF8+NUL/binary and independent array copies | Four data calls, trap after local array mutation, fresh unmodified binary recovery |

The packaged files are immutable captured inputs. A TypeScript imported array
is ordinary activation-local mutable data; it is not a read-only array or an
open filesystem stream. Rust slices are borrowed data, not host resources.
Closing/dropping one language-level reader is separate from proving physical
host-owner retirement. The programme checks both independent positions and
the existing physical/zero-active-owner samples. It does not advertise
concurrent callbacks or cross-tenant execution.

`tools/qualify_embedded_resources.py` builds only a fresh greeting using the
existing maintained builder, normally signs/admit it with four authenticated
companions, and retains every original named normal-programme activation.
The default-false `embedded_resource_conformance` runner selector adds one
post-tutorial probe without changing old paths or limits. Original grants and
provider bindings stay intact. Rust's reviewed CAS and complete native-vendor
graph are projected by the normal offline compiler into a fresh Cargo home;
there is no fetch against removed original path dependencies. Go's compiler
network must be denied. TypeScript consumes the
existing authenticated ordinary compiler tools and public engine, with no
native engine rebuild or new runtime selection.

The normal-bundle CLI requires exact current normal source/native/component
proof. A historical replay must authenticate its original producer, source,
five binaries, four companions and node receipt through a separately reviewed
adapter. It cannot manufacture a current normal receipt or relabel historical
compiled source. All new receipts bind actual compiler source inventories,
package inputs, materials, outputs, owner samples and shutdown.

Nine focused source/capture/protocol controls pass, including old text-only
Go embedding rejected by the broader asset-selection gate, missing transitive
edges, unselected npm data, removed NUL, false fresh output, live owners and
changed normal activation names. These are source controls. **The Go35 and TypeScript33 node programmes passed; the corrected Rust reference remains pending.** Existing compiler-level
missing/traversal/collision/limit/tamper controls and their shared production
paths remain distinct from runtime data observations.

The [Java resource observation](java-resource-conformance.md) already proves
its finite 39-outcome programme and real returned clock widths. The
[six-language resource matrix](packaged-resources.md) and
[standard facility matrix](standard-facilities.md) retain the broader #681
scope. AC3 resource/error coverage and AC8 concurrent/cancel/pending-flush/
late/fresh-cross-tenant requirements remain open; this candidate closes neither
the whole ticket nor those coupled runtime requirements.

## Targeted Go reference lane

The input-free20-minute `go-embedded-resource-reference.yml` job authenticates
completed run39373374237/job118465965449 and its exact public normal bundle
artifact12242839929 before restoring any executable. The merged maintained
producer validator allows only its enumerated unused-runner and native-test
postimages; this resource lane additionally requires its exact reviewed
resource selector. The original native producer and normal27 receipt stay
historical. Only one fresh greeting is built, normally signed/admitted, then
all original27 plus eight new calls are required.

Run39390308334/job118519971545 passed on frozen ba710. The
[source-bound observation](../testing/evidence/go-embedded-resources-signed-2026-10-20.json)
records35 known/reaped invocations,32 physical samples,14 zero-active-owner
samples and clean shutdown. All14 exercised material bytes equal merged2dbb
source; the fresh component and98-row source inventory are bound to their
actual build observation. Six exact data cases, explicit trap and fresh binary
recovery retained zero outbound/log/effect counts. Artifact12250800303's385
members passed CRC/hash verification. Native/companion ancestry remains94d;
no native rebuild or fabricated current normal qualification is claimed.

The job installs the already pinned componentize-go tool and Go1.27.2 compiler;
it does not rebuild latentd, the four companions or the original SDK baseline.
Public metadata/receipts and the fresh component are retained, with no demo
signing keys, compiler caches or GitHub credentials in the artifact. Twelve
source controls comprise the nine fixture/protocol cases and three replay
source/producer/workflow cases. This Go job supplies no pass for Rust or
TypeScript.

## Targeted Rust and TypeScript reference lanes

The separate 20-minute reference matrix in
`embedded-resource-languages-reference.yml` builds one greeting per language;
it preserves all existing authoring jobs. It reuses the same authenticated94d
native products through the maintained closed source-compatibility predicate.
Four companion components and their original normal receipt have separate
producer identities: Rust38 from run39358494292/artifact12236803645 and
TypeScript02f (compiled merge2cd6) from run39319524998/artifact12222984675.
The latter is the original captured-dependency normal30 programme, including
its three generator calls; it is not relabelled as the dependency-free27.

Acquisition checks the exact published artifact metadata, then reads only
fixed public companion/package layers and provenance through bounded HTTP
ranges. It excludes native executables, compiler caches, application source
payloads and signing keys. Each selected member passes ZIP CRC; pinned normal
qualification/source/node digests bind the four original component markers,
build observations and complete package-input manifests. The whole remote
archive is not downloaded or independently rehashed; the API archive digest
is recorded as metadata, separately from verified selected bytes.

Actual authenticated original receipts contain Rust27 invocations/24 physical
samples/six idle samples and TypeScript30/27/nine. Rust requires33/30/12. The
TypeScript original30 includes exactly three generator calls belonging to the
greeting that this resource fixture replaces. The replay preserves that full30
ancestry separately and projects only those exact calls at activation positions
12-14, physical positions10-12 and idle positions0-2. Every common27 call remains
required in its original order; the six fresh resource calls produce33/30/12.
Unknown, missing, reordered or extra calls fail. No historical receipt is edited.
Original component ancestry, selected native ancestry and fresh current
compiler/fixture source remain separate.

The first Rust-only reference at source `192c7b92` failed before compilation in
[job 118533625598](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/39394464486/job/118533625598):
the qualifier supplied the PATH `cargo` shim and the maintained regular-file
check returned `dependency-link-denied`. The correction supplies no explicit
Cargo path, selecting the existing captured-toolchain `rustup which` resolver.
The original refusal remains in the retained log and
[artifact 12254395006](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/39394464486/artifacts/12254395006).
The reference workflow now permits a manual `language=rust` retry; its default
and push selections still include both languages. This source correction is not
signed Rust execution evidence.

The next Rust reference at source `85db2200` passed native capture and removed
both original outside trees, then failed in the qualifier's extra data-only
`cargo fetch`: it reopened the original declaration's now-absent path. The
[failure artifact](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/39400521205/artifacts/12256023093)
retains that exact refusal before compilation. The correction requires the
reviewed closure and uses only the normal compiler's CAS/selected-manifest/
vendor projection with a fresh offline Cargo home. It checks the resulting
input identity and network-denied receipt; it does not restore old paths or
relax native dependency policy. Actual signed Rust execution remains pending.

The TypeScript node at source `192c7b92` completed all33 known/reaped calls,
30 physical samples and12 zero-active-owner samples with clean shutdown in
[job 118533626060](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/39394464486/job/118533626060).
Its outer job remains **failed**: the old report incorrectly expected the three
replaced-greeting generator calls, producing the superseded36-call expectation.
The [source-bound observation](../testing/evidence/typescript-embedded-resources-signed-2026-10-20.json)
records a separate exact report reprojection after authenticating the published
archive digest and all350 members. Exact UTF-8/NUL, binary, empty data, independent
copies, guest trap and fresh binary recovery passed with zero network/log/effects.
All10 exercised helper bytes match the original tested source; the fresh
component and61-row source inventory match their actual build observation.
The node's own source/binary before-after checks passed. The outer comparator
failed before its final integrity block, so this record claims neither that block
ran nor a new complete qualifier marker. No guest calls, native products or
historical qualification were rebuilt or relabelled for the report correction.
