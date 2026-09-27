# Source-backed documentation examples

## Outcome and boundary

Register a maintained example once, select a named source region in a public
Markdown guide, and build an inert code block with its source and verification
identity. This implements the registration/extraction contract in
[#351](https://github.com/KirilsTurkins/latent-service-fabric/issues/351).
Language-switching controls belong to
[#352](https://github.com/KirilsTurkins/latent-service-fabric/issues/352), and
publication/version snapshots to
[#353](https://github.com/KirilsTurkins/latent-service-fabric/issues/353).

This is development documentation tooling, not a new SDK, compiler, runtime
emulator or execution playground. The website reads source; it never executes
an example or its validation command. A successful site build is not a passing
client, transport, guest, containment or real-node test.

## Prerequisites and source ownership

Use the isolated, pinned Node/npm installation in the
[website instructions](website.md). The current prose remains in `docs/`.
Runnable examples stay in their owning SDK, application or guest projects.
`examples/guides/` contains only registrations, scenario instructions, and any
explicitly reviewed compact evidence records. Do not copy whole programs there.

The explicit [registry](../../examples/guides/registry.json) lists every allowed
`examples/guides/<scenario>/example.json`. There is no recursive source include
or discovery of credential/configuration files. The
[scenario schema](../../website/plugins/examples/scenario.schema.json) and
[registry schema](../../website/plugins/examples/registry.schema.json) are
versioned documentation-tooling contracts, not product resource schemas.

Each scenario specifies its ID, audience and execution target. IDs begin with
`client/`, `browser/` or `guest/`, and the audience must match. Each language
occurs at most once per scenario. A client TypeScript variant is explicitly
Node, not browser TypeScript; guest variants are explicitly components. Browser
registrations currently accept TypeScript only. The six syntax identifiers are
`rust`, `typescript`, `go`, `c`, `java` and `csharp`. A syntax identifier is not
proof of support for that execution target.

## Add a scenario

Add standalone region comments to the maintained source, without moving the
implementation into documentation. All six supported syntaxes use this
line-comment convention:

```text
// lsf-example-begin: invoke
    maintained source, with its existing indentation
// lsf-example-end: invoke
```

Names are lower-case identifiers with optional digits and hyphens. Markers must
occupy their own lines. Nested, duplicate, mismatched, unclosed, missing and empty
regions are rejected, including malformed markers elsewhere in a registered
source. Extraction removes only the two markers. It preserves indentation,
Unicode, internal blank lines, LF/CRLF and trailing newlines; it does not dedent,
format, translate or parse the programming language.

Create a registration following the
[maintained Rust example](../../examples/guides/rust-echo/example.json), then add
its path to the registry. Every variant lists its source, named regions, specimen
kind (`maintained`, `synthetic` or `test-double`), owning validation target path,
owner-instructions path and optional evidence reference. Validation targets are
file references, not shell command strings. The extractor never interprets or
executes instructions found there.

Select a region in a published **Markdown** page using a standalone comment:

```markdown
<!-- lsf-example: guest/rust-echo echo -->
```

Only actual comment nodes select data; this fenced authoring example is inert.
A misspelled scenario/region or malformed selection stops the build. Languages
without that region are omitted, never translated or silently substituted.

The maintained static renderer displays every available selected variant, its
execution environment/specimen kind, complete-source link, source/snippet hashes
and actual verification status. Source code becomes an AST code value, not an
interpolated Markdown fence, HTML node, evaluated import or MDX expression. JSX,
HTML, script-looking strings, backticks and language comments stay code.

## Maintained guest scenario

The [Rust echo fixture](../../examples/echo-contract/README.md) owns this real
implementation. It is a guest/component example, **not** a network-client guide.
Its existing instructions explain the byte limit, declared errors, best-effort
logging, build commands and trust boundary. Those facts are not redefined here.
The registration currently has no matching compact evidence record, so the site
honestly reports **source extraction only**. Historical phase evidence is not
silently promoted into a new per-source passing badge.

<!-- lsf-example: guest/rust-echo echo -->

## Verification records and uncertainty

Evidence is optional. `null` means extraction only. A supplied reference names
one approved JSON record and its exact SHA-256. Records follow the
[evidence schema](../../website/plugins/examples/evidence.schema.json): scenario,
language, exact source checkpoint, source and validation-target hashes, level,
execution kind, pass/fail, toolchain, run and scope are all required.

The website verifies the referenced record hash and matches the displayed source
and target bytes to that checkpoint using local Git object identities. It never
fetches a missing commit. A record may use an earlier checkpoint when those exact
source and target bytes still match; documentation corrections do not need to
pretend they were present in the original runtime/source commit.

Missing, malformed, failed, hash-mismatched or unavailable evidence remains
`source-extracted` with an explicit reason. A synthetic fixture cannot become a
qualified implementation. Test-double/compilation evidence cannot be relabelled
`real-node`. Compilation/local tests and real-node conformance remain different
levels, with execution kind and actual scope retained. The displayed statement
is a **reviewed record**, not an independently rerun or cryptographically certified
result. Never fabricate a passing record to make a guide look complete.

The source owner runs the existing language-native checks separately and retains
an attributable, redacted record. Do not put tokens, private endpoints, raw logs,
secret outputs or benchmark archives in registrations/evidence. These are trusted,
reviewed build inputs, not a sanitizer for malicious authors or a sandbox for
concurrent hostile checkout modifications.

## UI and publication handoff

The pure [typed resolver](../../website/plugins/examples/resolve.d.mts) accepts
`resolveExample(bundle, {documentVersion, example, region})`. Callers must supply
the actual document version; there is no implicit development fallback. The
bundle separately records `documentVersion`, `documentationRevision`,
`sourceRevision` and an input digest. Each selected variant carries source bytes'
SHA-256, snippet SHA-256, line span, full-source URL and verification details.

The Docusaurus plugin exposes only referenced regions through `lsf-examples`
global data. The same bounded JSON is written, content-addressed, under ignored
`website/.generated/examples/`. The full registry, source bodies, absolute build
paths, unreferenced regions, evidence files and private input inventory are not
copied into public assets. There is no new static asset directory or remote
example service.

The request collector already recognizes an MDX `CodeExample` element with only
literal `example` and `region` attributes for #352. It rejects expression-valued
attributes, spreads, duplicates and arbitrary include paths. The component is
not implemented by this ticket; ordinary guides use the static comment form
above until that UI lands. The collector leaves component nodes intact for the
component owner, while supplying their requested validated data.

Snapshot tooling consumes this exact bundle/resolver contract. It must choose
and retain each version's bundle, not import changing SDK source at runtime.
Non-development extraction rejects source or reference bytes that do not match
the declared revisions. Development previews allow changed working-copy source
but omit misleading commit-bound links and downgrade its evidence. Committed
publication builds retain exact complete-source links. The versioning child owns
release selection, correction manifests, retention and publication rollback.

## Limits, invalidation and recovery

| Resource | Fixed maximum |
|---|---|
| Scenario registrations / variants per scenario | 64 / 6 |
| Regions per source / public region requests | 32 / 256 |
| Distinct input files / aggregate input bytes | 512 / 8 MiB |
| Source/reference file / registry or evidence metadata | 256 KiB / 16 KiB |
| One extracted region / public JSON output | 32 KiB / 1 MiB |

Paths must be explicit, correctly cased, repository-relative ASCII paths without
traversal, hidden segments, encoded separators, drive/stream syntax or reserved
Windows names. Linked ancestors/files, directories/devices as sources, malformed
UTF-8, NUL and BOM are rejected. Source roots and language extensions are
allowlisted; credentials and arbitrary configuration formats are not source
includes. Optional evidence absence does not excuse an unsafe or linked path.

Source/registration/evidence identity contributes to the MDX cache key and site
manifest. Production builds and built-site validation check both the current
example identity and the actual rendered code/source links. A source-only change
cannot reuse an old successful example result. During development, **restart the
website command after changing registrations, references or source regions**.
The plugin fails rather than presenting stale startup data when these inputs
change during a build; no background executor or custom watch service is added.

Snapshot output is create-only and verified on reuse. An interrupted partial file
or altered existing output fails with a collision diagnostic. Stop the build,
remove only its reported ignored generated file (or the examples output directory)
and rerun. Do not overwrite committed release snapshots or delete historical
runtime evidence to recover a local documentation build.

## Validation and cleanup

From `website/`, with its pinned dependencies installed:

```sh
npm run check
npm test
npm run build
npm run build:root
npm run test:build
```

The standard suite includes extraction/schema/negative tests and an actual
Markdown/MDX-to-React static-render integration test using the existing pinned
dependencies. Both production builds enforce source freshness, snippet text and
commit-bound links. No six-language installation or real node is needed.

The dependency-free portion can also run directly:

```sh
node --test tests/examples.test.mjs tests/example-render.test.mjs tests/example-source.test.mjs
```

Those focused checks are not substitutes for the pinned integration/build suite.
The six generated syntax fixtures and their matching-evidence fixtures are
explicitly synthetic; no client, compiler or node is launched. They cover broken
paths/regions, unreferenced content, Unicode and dangerous-looking code, limits,
determinism, evidence failure/downgrade, two distinct version bundles and exact
source identities. The real Rust registry/region also has a direct regression.

Changing executable example source still selects its normal owning product tests
through the existing CI classifier. This ticket changes neither that classifier
nor runtime budgets or client retry/cancellation semantics. Build outputs are
ignored; temporary test repositories are removed on completion. Leave the
continuous documentation milestone open after this infrastructure is accepted.
