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
provider bindings stay intact. Rust's locked data-only fetch precedes the
offline build; Go's compiler network must be denied. TypeScript consumes the
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
changed normal activation names. These are source controls. **The new Go,
Rust and TypeScript signed programmes are pending.** Existing compiler-level
missing/traversal/collision/limit/tamper controls and their shared production
paths remain distinct from runtime data observations.

The [Java resource observation](java-resource-conformance.md) already proves
its finite 39-outcome programme and real returned clock widths. The
[six-language resource matrix](packaged-resources.md) and
[standard facility matrix](standard-facilities.md) retain the broader #681
scope. AC3 resource/error coverage and AC8 concurrent/cancel/pending-flush/
late/fresh-cross-tenant requirements remain open; this candidate closes neither
the whole ticket nor those coupled runtime requirements.
