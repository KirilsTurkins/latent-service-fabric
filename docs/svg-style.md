# Documentation SVG convention

This is the visual and accessibility reference for every checked-in SVG in
Latent Service Fabric. Today, those SVGs are source-controlled explanatory
documentation diagrams, including normal repository Markdown and the managed
GitHub Wiki. They must clarify a documented relationship and never act as the
only source of a normative claim.

## Where visuals belong

- Store repository-documentation assets under [`assets/`](assets/).
- Store managed Wiki assets under `wiki/pages/assets/` when working on the Wiki
  source branch.
- Use lowercase kebab-case filenames that describe the relationship shown, such
  as `phase0-gate-decision.svg`.
- Embed a local asset with descriptive Markdown alt text. Keep the surrounding
  prose authoritative and update the visual in the same change when its meaning
  changes.

Do not use remote images, raster screenshots, Mermaid-only diagrams, embedded
HTML, JavaScript, event handlers, external stylesheets, or external fonts.

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
the image. Prefix every internal ID (`example-arrow`, `example-shadow`) with
the filename concept to avoid collisions if a renderer inlines SVG content.
Keep text as real SVG `<text>` elements rather than flattening it into paths.

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

The palette continues the managed Wiki's existing purple–blue visual language.
Use colors by meaning, not decoration.

| Meaning | Fill / accent | Text | Use |
|---|---|---|---|
| Canvas | `#1b102d` → `#1e3a5f` gradient | `#faf5ff` | Every standard dark diagram background |
| Evidence or local execution | `#312e81`, `#1e40af`, or `#7c3aed` → `#2563eb` | `#f8fafc`, `#e0e7ff` | Facts, bounded components, and verified inputs |
| Connector | `#bfdbfe` | — | Directional arrows and neutral relationships |
| Blocked or work required | `#78350f` / `#fbbf24` | `#fde68a` | Gate blockers, warnings, and unresolved work |
| Verified pass or authorized result | `#065f46` / `#34d399` | `#d1fae5` | Use only when the surrounding authoritative text supports it |
| Outside scope or later work | `#1e293b` / `#64748b` | `#cbd5e1` | Planned, excluded, or non-claimed capability |

Use a subtle dark drop shadow (`#09090b` at roughly 0.38 opacity) for primary
cards, 2 px borders, and sufficient text contrast. Do not use green merely to
make a diagram feel positive: it is reserved for a verified or authorized
state. Likewise, a closed issue must not be drawn as an authorization signal.

## Truth, motion, and review

- Make the title and description describe the current relationship, not an
  aspirational one. A diagram may show both branches of a decision when one
  branch is not currently satisfied.
- Pair the SVG with nearby prose that states status, scope, and exceptions.
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

The initial assets in [`assets/`](assets/) are the reference implementations
for this convention.
