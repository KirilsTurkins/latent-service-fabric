# Immutable packaged resources

Declare immutable files in `capsule-resources.json`. The six maintained builders
use the same exact-byte package assembler. It reads captured project files and
selected dependency resources; it never reads a new host path during assembly.

```json
{
  "schemaVersion": "lsf.packaged-resources.v1",
  "resources": [
    {"path": "data/messages.txt", "source": "assets/messages.txt", "mediaType": "text/plain"}
  ]
}
```

Logical names must be NFC-normalized relative paths without traversal, encoded
separators, device names or trailing-dot/space aliases. Case aliases, ambiguous
directory prefixes and file/directory collisions are rejected. The profile
allows 256 resources, 256 UTF-8 bytes per logical name, 16 path segments, 8 MiB
per file and 32 MiB across declared logical resources. Media types contain no
parameters. Bytes are retained exactly; assembly does not decode text, repair
invalid text or infer an encoding.

The device-name restriction also covers COM/LPT names containing superscript
digits ¹, ² and ³, including names with extensions and directory segments.
[Windows reserves these aliases](https://learn.microsoft.com/en-us/windows/win32/fileio/naming-a-file)
even though they are normalized Unicode. Other valid Unicode resource names
remain supported. Undeclared files are not selected or packaged.

The package contains `resource-index.json` and digest-named objects under
`resources/objects/`. The index records each logical name, media type, size,
digest and application/dependency origin. Equal byte sequences share an object.
Its identity binds the source snapshot, declaration manifest, reviewed dependency
lock, component and selected resource inventory. The ordinary signed package
and build observation cover the index and objects as assets. Missing, changed,
unlisted or incorrectly attributed bytes fail verification. Index rows are in
logical-path order; verification rejects a rehashed index with a different order.

The developer workflow derives a `resourceInputs` manifest binding and includes
the manifest and its declared source files in trust/watch snapshots. Changing
resource selection invalidates approval; changing resource bytes changes the
source/build cache identity. Snapshot acceptance verifies presence, path rules,
collisions and byte limits before advancing accepted state. Excluding a required
resource input or omitting its trust binding fails. The developer controller's
source-transfer limits also apply.

Language ingestion can add a selected transitive resource by supplying its
logical name, staged source, media type, digest and captured artifact owner. Its
bytes and size must occur in that owner's reviewed dependency file inventory.
A package name alone cannot make an unobserved file a trusted resource.

| Language | Compile-time data path | Standard runtime lookup qualification |
| --- | --- | --- |
| Rust | Captured data selected by `include_bytes!` / `include_str!` | No general runtime filesystem lookup advertised |
| C | Captured constant data / selected compiler resource inputs | Runtime resource facade still requires component evidence |
| TypeScript | Captured bundled asset modules | Dynamic asset lookup still requires component evidence |
| Go | Captured `//go:embed` data | Exact embedded lookup APIs still require component evidence |
| Java | Captured selected classpath resource bytes | Selected `Class.getResourceAsStream` and direct `ClassLoader.getResourceAsStream` signed-node cases; broader lookup APIs pending |
| .NET | One verified selection supplies package layers and embedded compiler inputs | `Assembly.GetManifestResourceStream` runs in the focused signed resource fixture; broader library/distribution acceptance remains open |

The [.NET resource and explicit wall-clock reconciliation](https://github.com/KirilsTurkins/latent-service-fabric/blob/200c17c26b24d6bf06d8d28102362ea714c1f4eb/docs/development/phase4-handoffs/2026-10-12/pr856-reconciliation.md)
records fresh signed-node checks for binary/empty resources, literal names,
independent stream positions, absent lookup and disposal. Those checks do not
qualify every NuGet library or a new packaged toolkit. Java's selected class and
classloader lookup cases require current-head emitted-component qualification;
other Java lookup APIs remain outside that finite evidence.

This table identifies the ingestion paths and their runtime acceptance boundaries;
package assembly alone does not prove those APIs execute. The index records
`runtimeLookup: language-profile-qualification-required`. Each language owner
must qualify the unchanged standard API in a signed admitted component, including
transitive data, outside-checkout/offline and lifecycle cases, before advertising
that path as supported. A runtime lookup cannot resolve dependencies or fall
back to the host filesystem.

Scratch storage is separate and currently unsupported by this resource profile.
It grants no writable filesystem, temporary directory, durable state, ambient
clock, entropy or logging authority. Resource packaging introduces no scheduler
or background worker. Runtime stream closure, concurrent access and retirement
remain subject to the language runtime and activation-ownership qualification.

Related: [captured dependencies](application-dependencies.md),
[compatibility reports](library-compatibility.md), and
[guest SDK development](guest-sdk.md).
