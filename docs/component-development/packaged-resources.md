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

The package contains `resource-index.json` and digest-named objects under
`resources/objects/`. The index records each logical name, media type, size,
digest and application/dependency origin. Equal byte sequences share an object.
Its identity binds the source snapshot, declaration manifest, reviewed dependency
lock, component and selected resource inventory. The ordinary signed package
and build observation cover the index and objects as assets. Missing, changed,
unlisted or incorrectly attributed bytes fail verification.

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
| Java | Captured selected classpath resource bytes | `getResourceAsStream` integration and emitted component tests pending |
| .NET | Captured selected embedded resource inputs | `GetManifestResourceStream` integration and emitted component tests pending |

This table identifies the ingestion paths and outstanding runtime acceptance;
package assembly does not prove those APIs execute. The index records
`runtimeLookup: language-profile-qualification-required`. Each language owner
must execute the unchanged standard API in a signed admitted component, including
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
