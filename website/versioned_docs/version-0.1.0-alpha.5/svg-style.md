# Documentation SVG convention

This is the visual and accessibility reference for every checked-in SVG in
Latent Service Fabric. Maintained explanatory diagrams use the same semantic
palette as the website. Historical diagrams retain their original bytes and
claims. Every illustration must clarify a documented relationship and never
act as the only source of a normative claim.

## Where visuals belong

- Store repository-documentation assets under [`assets/`](assets/).
- The legacy Wiki source snapshot is inventoried separately below. Do not
  import another generator or change its publisher through a palette refresh.
- Use lowercase kebab-case filenames that describe the relationship shown, such
  as `phase0-gate-decision.svg`.
- Embed a local asset with descriptive Markdown alt text. Keep the surrounding
  prose authoritative and update the visual in the same change when its meaning
  changes.

Do not use remote images, embedded HTML, JavaScript, event handlers, external
stylesheets or external fonts in SVGs. Canonical diagrams are not raster
screenshots. Dated browser-review PNGs under `website/evidence/` are tooling
evidence, not replacement diagrams or automatically published image assets.
Website Mermaid helpers require adjacent authoritative prose, reviewed source,
the shared palette and a static readable result; they are not the only form of
a normative diagram. The initial website flowchart uses strict rendering and
SVG text rather than HTML labels. Other Mermaid diagram types require their
own visual qualification rather than inheriting a blanket contrast claim.

## Required SVG structure

Every SVG must be valid XML and begin with this accessibility contract, using a
file-specific ID prefix:

```xml
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1440 760"
     role="img" aria-labelledby="example-title example-description">
  <title id="example-title">Short visual title</title>
  <desc id="example-description">Complete plain-language description of the relationship shown.</desc>
  <!-- defs and drawing elements -->
</svg>
```

Use a `viewBox`, not fixed `width` or `height`, so Markdown renderers can scale
the image. Every nonempty ID must be unique within its SVG document; duplicate
IDs make local references ambiguous. The validator scopes this uniqueness check
to one file at a time. Prefix every internal ID (`example-arrow`,
`example-shadow`) with the filename concept to avoid collisions if a renderer
inlines SVG content. Keep text as real SVG `<text>` elements rather than
flattening it into paths.

## Local resources and supported CSS

[`tools/svg_references.py`](../tools/svg_references.py) owns resource checking
for the repository SVG validator. The documentation validator reuses that same
path; it does not maintain a second SVG policy. All IDs are collected before
references are checked, so a definition may follow its use. References are
case-sensitive and scoped to one SVG: a definition in another file never
satisfies a missing local ID. Duplicate IDs remain an error independently of
reference checking.

`href` (including namespaced `xlink:href`) and `src` must contain a nonempty
literal fragment such as `#example-arrow`. Every CSS `url(...)` must likewise
name an existing local ID. This covers presentation attributes such as `fill`,
`stroke`, `filter`, `clip-path`, `mask` and marker properties, inline `style`
attributes, and each `<style>` block. The helper's `CSS_ATTRIBUTES` set records
the checked presentation attributes; animation `from`, `to`, `by` and `values`
retain the resource tripwire too. Ordinary metadata such as `aria-label`, `id`
and `data-*` is not interpreted as CSS.

External URLs, `data:` URLs, protocol-relative URLs and cross-file references
are rejected, including `this-file.svg#example-arrow`. Empty references, bare
`#` and missing IDs are errors. A nonempty `xml:base` is unsupported because it
could redirect otherwise local-looking fragments. The checker never fetches
references, reads target files, executes CSS/SVG or rewrites an asset.

The static-diagram CSS subset has these explicit rules:

- Literal `url` is case-insensitive. Unquoted, single-quoted and double-quoted
  arguments are accepted, including ASCII whitespace around the argument:
  `url(#example-arrow)`, `URL( '#example-arrow' )` and
  `url( "#example-arrow" )`. IDs themselves cannot contain whitespace. Multiple
  URLs and URLs inside ordinary nested functions are checked in source order.
- Terminated `/* ... */` comments between tokens are ignored. Ordinary quoted
  strings are inert rather than mistaken for URL/import tokens. Comments never
  join identifier tokens. The `url` name must immediately precede `(`; a
  whitespace/comment-separated spelling is rejected rather than repaired.
  Comments inside an unquoted URL or between a quoted argument and its closing
  `)` are explicitly unsupported, not stripped. Comment-like characters inside
  a quoted URL are literal characters and must match the referenced ID.
- CSS backslash escapes outside comments are explicitly rejected, including
  escaped function names, import keywords, strings and fragments. Fragment IDs
  must be literal: percent encoding, additional `#`, parentheses/SVG view
  specifications and control characters are unsupported. XML character
  references are checked after the XML parser decodes them.
- `@import` is always rejected, regardless of target or case. Indirect resource
  functions `image()`, `image-set()`, `-webkit-image-set()`, `src()` and `attr()`
  are outside this subset; use literal `url(...)` references instead.
  Unterminated strings/comments/URLs, malformed URL arguments and unmatched or
  unclosed delimiters fail explicitly. There is no browser-style error recovery.

Diagnostics include the file, the offending reference or syntax excerpt, and
its element/attribute context. CSS offsets are zero-based character positions
within that XML-decoded attribute or style block. A malformed source fails
closed without preventing checks of other attributes, style blocks or files.
This is a resource tokenizer, not a complete CSS property/selector/cascade
validator, animation validator, renderer or sanitizer for arbitrary hostile SVG.
The existing accessibility, forbidden-element and event-handler checks remain
separate requirements.

With the pinned Python environment and `tools/requirements.lock` installed,
run the focused suite from the repository root:

```sh
PYTHONPATH=tools python -m unittest tools.tests.test_svg_references tools.tests.test_validate_repository tools.tests.test_validate_docs
python tools/validate_repository.py
python tools/validate_docs.py
```

The tests exercise both validation paths, including real marker, filter and
gradient definitions in `phase2-delivery-boundary.svg`, without changing source
asset bytes. Existing contract-test discovery and documentation CI own these
checks; no extra workflow or rendering dependency is required.

## Layout and typography

Use the 1440 × 760 wide canvas for flows, decision diagrams, and architecture
boundaries. A smaller canvas is acceptable only when its aspect ratio makes the
relationship clearer. Keep a 72 px outer margin, 24 px rounded cards, and a
clear left-to-right or top-to-bottom reading direction.

Use the renderer-safe type stack `system-ui, sans-serif` and these size tiers:

| Role | Weight and size | Purpose |
|---|---|---|
| Heading | 700, 34 px | Single statement of the visual's point |
| Subheading | 400, 18 px | Scope or qualification |
| Card title | 700, 21 px | Named step, component, or decision |
| Card copy | 400, 15 px | Short factual detail |
| Supporting label | 600, 14 px | Commands, notes, and constraints |

Prefer short labels and several aligned text lines over dense paragraphs.
Arrowheads and connectors must make direction unambiguous without relying on
color alone.

## Shared palette and semantic color

[The semantic palette](assets/lsf-palette.json) is the sole color authority for
maintained presentation. Its amber, gold and warm charcoal are original LSF
styling; no game artwork, logo, character, font or layout is imported.
The website generates CSS and Prism colors from this file. The narrow
[Python helper](../tools/illustration_palette.py) checks current diagrams against its **dark** tokens; ordinary SVG checks do not
need Node. Current diagrams are self-contained, hand-authored SVGs.

| Meaning | Surface / outline token | Foreground token | Use |
|---|---|---|---|
| Canvas | `canvas` to `surface` | `text`, `muted` | Explicit embedded dark background |
| Bounded component | `surface` or `raised` / `border` | `text`, `link` | Neutral facts and named owners |
| Connector | `link` | Not applicable | Direction also encoded by arrowheads |
| Cleanup cannot be proved | `warningSurface` / `warningBorder` | `warningText` | Named quarantine branch, not gold-only status |
| Cleanup proved safe | `successSurface` / `successBorder` | `successText` | Named release branch, not implied authorization |
| Outside scope or later work | `raised` / `border` | `muted` | Explicit planned/excluded labels |

Parent-page CSS does **not** theme an external SVG image. These SVGs keep the
same opaque dark representation on light and dark GitHub/website pages, rather
than relying on inherited CSS variables, external fonts or filters. Use external images and file-specific IDs to avoid fragment collisions.

Text pairings must reach 4.5:1; applicable boundaries, arrowheads and controls
must reach 3:1. Large text may use the WCAG 3:1 threshold, but the maintained
presentation text is checked at the stronger 4.5:1 threshold. Shadows are only
decorative. The approved site pairings and exceptions are documented in the
[theme contract](development/website-theme.md); the
[text](https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html) and
[non-text](https://www.w3.org/WAI/WCAG22/Understanding/non-text-contrast.html)
criteria do not make an unchecked color combination accessible.

## Inventory and preservation

[The inventory](assets/illustrations.json) must cover **every tracked SVG**,
including future branding or migrated content, not only an `assets/` glob.
An unclassified new SVG fails the scoped check. Current dispositions are:

| Source / output | Disposition | Maintained owner |
|---|---|---|
| `phase0-gate-decision.svg` | Immutable dated gate; historical completion page keeps original | Exact SHA-256 in inventory |
| `phase0-scope-boundary.svg` | Immutable historical measured scope | Exact SHA-256 in inventory |
| `phase0-resource-lifecycle.svg` | Immutable historical composition | Exact SHA-256 in inventory |
| `phase1-delivery-boundary.svg` | Immutable historical handoff and measurement statements | Exact SHA-256 in inventory |
| `phase2-delivery-boundary.svg` | Immutable historical boundary; dated completion review keeps original | Exact SHA-256 in inventory |
| `activation-lifecycle.svg` | Maintained current activation and cleanup behavior | Hand-authored; palette checked by `tools/illustration_palette.py` |
| `package-delivery.svg` | Maintained current capsule, static-site and SSR delivery | Hand-authored; palette checked by `tools/illustration_palette.py` |

There are no tracked vendor/brand SVGs or migrated Wiki SVGs in this initial
inventory. The two legacy Wiki SVGs (`architecture-at-a-glance.svg` and
`system-decomposition.svg`) and their CairoSVG/Pillow generator are recorded at
exact `docs/wiki` source revision
`d1035a50d2fd99b076c74dd958ca4437d909f2ec`, with Git blob identities. Their dated
Phase 2 statements are **not** republished as current runtime facts. No Wiki
generator or GIF is imported. [Issue 356](https://github.com/KirilsTurkins/latent-service-fabric/issues/356)
owns selective migration and publisher retirement; any later editable migration
must select one maintained owner and enter this inventory. This is not a claim
that the live Wiki is already retired or completely audited.

The five originals are exact, individually documented historical palette
exceptions, not a wildcard waiver for new purple/blue presentation. Benchmark,
measurement, signed/digest-bound, release-snapshot and upstream/vendor bytes are
not recolored. Current guides and the README use current diagrams with current claims. Historical
illustrations belong only with dated developer evidence. Recoloring an old
diagram does not make its feature claims current; the obsolete presentation
copies have been removed.

## Regeneration and focused checks

From the repository root:

```sh
python tools/illustration_palette.py
python -m unittest tools.tests.test_illustration_palette -v
```

After reviewing a semantic token change, update the two current SVGs and inspect
their rendered labels and geometry. Their explicit `maintained` inventory entries
name their owners and current consumers. The helper checks every literal color
against the shared palette and rejects unknown assets or missing consumers.

Historical and released-snapshot SVG hashes remain checked independently.
The optional color-only copier can regenerate explicitly inventoried copies;
there are currently none. It cannot update technical claims and must not be used
to present an earlier product boundary as current. `--check-legacy` checks the
recorded Wiki blob identities if that snapshot exists locally; it never fetches
or runs the old generator.

Run the existing `tools/validate_repository.py` SVG contract as well; this helper
does not replace its security/accessibility/resource-reference ownership.
Website commands and rendered light/dark, narrow and full-size/zoom review are
in the [theme instructions](development/website-theme.md). A narrow embedded
1440-pixel diagram is an overview, not readable body text: provide a full-size
image link and preserve the prose explanation. Two-dimensional diagrams need
inspection/zoom; do not shrink text and call it mobile accessibility.

## Truth, motion, and review

- Make the title and description describe the current relationship, not an
  aspirational one. A diagram may show both branches of a decision when one
  branch is not currently satisfied.
- Pair the SVG with nearby prose that states status, scope, and exceptions.
- Mark historical gate diagrams with their phase and date. Preserve their
  measured claims without presenting them as the current delivery boundary;
  [the Phase 1 overview](assets/phase1-delivery-boundary.svg) shows the completed
  standalone scope and later-phase features separately.
- Prefer static diagrams. If motion is ever necessary, it must be decorative,
  must not carry unique information, and must respect reduced-motion users.
- Before committing, verify XML parsing, a non-empty `title` and `desc`, the
  `viewBox`, local Markdown links, and that no scripts, remote resources, or
  unsafe URI schemes appear in the asset.

`tools/validate_repository.py`, which runs through the repository contract
validation, enforces the structural portion of this convention for every SVG
in the repository source tree: XML parsing, the accessibility contract,
title/description labels, local-only references, and the absence of active
content. The layout and color rules above remain a deliberate review standard.

The current delivery and activation diagrams are the palette references.
The five archived originals retain their historical scope and bytes.
