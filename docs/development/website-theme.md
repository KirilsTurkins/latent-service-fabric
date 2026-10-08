# Website theme and illustration review

This is the bounded presentation contract for documentation children
[#349](https://github.com/KirilsTurkins/latent-service-fabric/issues/349) and
[#350](https://github.com/KirilsTurkins/latent-service-fabric/issues/350).
It does not accept practical guides, language controls, snippets, version
snapshots, Wiki migration, search, deployment or runtime capability. The finite
coverage rows and human reviews remain pending until their own evidence passes.

## One palette, explicit contexts

[`../assets/lsf-palette.json`](../assets/lsf-palette.json) is documentation tooling
data, not a runtime resource schema. Its forty roles in each light/dark mode are
checked by the local [schema](../../website/content/palette.schema.json).
[`palette.mjs`](../../website/lib/palette.mjs) validates 128 explicit pairings,
generates a content-addressed CSS file under ignored `website/.generated/theme/`,
and supplies Prism colors and the initial Mermaid flowchart configuration.
There is no independent hand-maintained CSS hex palette or external font/image.

| Foreground role | Approved background / context | Required contrast |
|---|---|---|
| `text`, `muted`, `link`, `linkHover` | `canvas`, `surface`, `raised` | 4.5:1 |
| Every `code*` syntax foreground | `codeSurface`, highlighted `raised` line | 4.5:1 |
| `controlText` | `controlSurface`, `controlHover` | 4.5:1 |
| `disabledText` | `disabledSurface`; disabled label and dashed border retained | 4.5:1 even though inactive controls have an exception in WCAG |
| `tabText`, `selectionInk`, `accentInk` | Their respective selected/accent surfaces | 4.5:1 |
| Status `*Text` | Matching `success`, `warning`, `danger`, `info` surface | 4.5:1 |
| `focus`, `border`, `controlSurface`, `controlHover`, `tabSurface` | Adjacent ordinary reading surfaces | 3:1 |
| `focus` | `codeSurface` and every status surface | 3:1 |
| Status `*Border` | Matching status surface and canvas | 3:1 |

Gold is an accent and dark-mode control surface, **not** normal text on cream.
Light-mode links use dark brown ink. Green, red and blue are deliberate semantic
status exceptions: every callout also has an icon and a visible label. Selected
tabs have an underline and `aria-selected`; disabled controls use native
disabled semantics, a label and dashed border rather than reduced opacity.
Links in prose remain underlined. Opaque text selection has its own pairing.

The generated CSS only sets semantic variables. The small
[stylesheet](../../website/src/css/theme.css) maps those variables onto Infima
and global Docusaurus component classes. No theme implementation is copied or
swizzled. The one pinned narrow selector for code-line-number `::before` restores
normal-text contrast instead of the upstream 0.4 opacity; its computed opacity
and pairing are browser-tested. Re-review that selector on a Docusaurus upgrade.

System preference and explicit light/dark choice use Docusaurus's maintained
color-mode initialization and keyboard control. First contentful paint with
React hydration held, and persisted-theme reload, are checked rather than only
the hydrated final state. The painted canvas includes the HTML background when
the body is transparent. Supported standard tabs move
focus with arrow keys and select with Enter. This is not the future language
preference component. Focus has a 3-pixel offset outline, scroll spacing and a
forced-colors fallback. Navigation, tab, disclosure and form specimens use
native/supported semantics; motion is absent by default and disabled under
reduced motion. [Docusaurus styling](https://docusaurus.io/docs/styling-layout)
is the upstream extension boundary.

## Site versus illustration ownership

The site changes with the selected mode. Maintained external SVGs and the initial
Mermaid flowchart use a **fixed dark, explicitly colored panel** so their meaning
does not depend on inherited page CSS. Mermaid uses the supported base-theme
variables, strict rendering and SVG text (`htmlLabels: false`); its initial
flowchart is tested in both site modes. Do not infer blanket qualification of
every future Mermaid diagram type.

Use Mermaid's root-level `htmlLabels` option, not the deprecated flowchart-only
setting: the [upstream configuration schema](https://mermaid.js.org/config/schema-docs/config.html)
gives the root option precedence. The browser check rejects `foreignObject`
labels and measures the actual SVG text, rather than trusting configuration alone.

The [SVG convention and inventory](../svg-style.md) bind all five immutable
originals, two maintained presentation copies and the read-only legacy Wiki
source assessment. Changing a token reveals new generated CSS identity and a
stale presentation-output check until the named copies are regenerated/reviewed.
It never automatically rewrites old evidence or versioned assets. Palette data,
source MDX and local build configuration remain reviewed executable inputs;
these tests are not a sandbox for untrusted authors.

## Reproduce without a runtime build

Use the pinned website Node/npm toolchain in the [foundation instructions](website.md).
From `website/`:

```sh
npm ci --ignore-scripts --no-audit --no-fund
npm run check
npm test
npm run build
npm run build:root
npm run browser:install
npm run test:build
npm run test:theme
```

Run the focused Python illustration commands from the repository root as well.
The npm dependency graph is unchanged by these children. No Cargo, runtime,
provider, SDK, Angular or benchmark build is needed for this qualification.
The website remains isolated; this work adds **no workflow**. Existing CI can
be green without running the website: [#355](https://github.com/KirilsTurkins/latent-service-fabric/issues/355)
still owns the scoped maintained website profile and protected publication.

`/components/` is the site-relative component review route (prepend the configured
base URL). It includes code, every syntax role, selected tabs, all callouts,
tables, a keyboard disclosure and active/disabled/form controls, clearly labelled
as a UI fixture. It is not a page-existence proxy for teaching quality.

`test:theme` serves the actual production outputs on bounded loopback servers,
with same-origin requests only. It checks computed text colors, code line
numbers, hover/selection, a deliberately invisible-text negative canary, system
and stored themes, keyboard focus/navigation, mobile layout, 200% equivalent reflow, reduced motion,
Mermaid and before/after SVG rendering. Both project and root base paths are
required. SVG labels, viewBox boundaries and markers are checked; originals and
copies are inspected as external images, including narrow embedding and full-size
zoom. It writes compact evidence and screenshots under
`website/.generated/theme-review/`; stale source identities fail the underlying
built-site check. A timeout/interrupted test is neither a pass nor proof of failure
in the product.

The control review independently samples the active button, both tabs, text
field and select at rest, with the button hovered, and after tab selection. It checks value text as well as
boundaries: input values are not text nodes, and a text-node walk alone does
not qualify native fields. A filled control must contrast with its adjacent surface,
or its four visible border sides must do so. This is the theme's explicit
solid-control contract, not a claim that WCAG requires an outline on every
text-only button. Two rendered negative canaries remove a field boundary and
hide its value text; both must fail before evidence is written. Disabled controls
retain their separate labelled specimen; the native checkbox is exercised with
Space and checked for visible focus. Native checkbox glyphs and select popups
still require platform-specific visual review. Gradients, opacity, filters,
blending and masks fail closed in this bounded control sampler rather than being
silently certified. The evidence records the actual platform, architecture, OS
release and Node version instead of assuming the initial Windows review host.

The shared contrast arithmetic, computed-color parser, control sampler and
negative assertions also have dependency-free unit tests:

```sh
node --test tests/contrast.test.mjs tests/control-review.test.mjs tests/theme-review.test.mjs
```

These focused tests do not replace the pinned production builds or browser
suite above. They do not establish native zoom or complete accessibility.

The responsive fixture additionally uses a 640 CSS-pixel viewport. A separate
**200% rendering-equivalent** check uses 640 by 450 CSS pixels at device-pixel
ratio 2, producing the layout and physical screenshot dimensions of a 1280 by
900 viewport at 200% zoom. It verifies the dimensions, reflow, reading and
mobile navigation in both modes and base paths. This is not native browser
zoom: operating-system/browser controls remain a manual acceptance check.
The pinned full Chromium could not navigate even a local production page on
the initial Windows review host, with or without a test extension; those
timeouts are not passes and do not establish a product failure. The unqualified
extension harness is not retained or required by the working headless-shell
suite. No test accesses a user's browser profile or changes an OS setting.
The test has a five-minute total deadline and closes its own browser/servers.
SVG inspection also doubles the full-size image width. Retain dated screenshots and manual
observations with the exact reviewed checkpoint; automated checks do not certify
all accessibility, browsers, assistive technologies or future content. See
[WCAG reflow](https://www.w3.org/WAI/WCAG22/Understanding/reflow.html) for the
distinction between ordinary reading content and two-dimensional diagrams.
