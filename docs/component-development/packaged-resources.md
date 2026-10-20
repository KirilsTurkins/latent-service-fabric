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
An application-origin row requires a bound declaration-manifest digest; a
dependency-origin row requires a bound dependency-lock digest. Rehashing an
index cannot replace either missing input binding by relabelling the origin.
Application-only, dependency-only and mixed selections retain the same exact
byte/object inventory rules.

Verification of an application selection requires the actual declaration bytes
through the explicit `manifest` input, including a declared-empty selection. The
bytes must match both the externally supplied manifest digest and the index
binding before decoding, within the existing 256 KiB document bound. The verifier
uses the capture schema, path, collision and count checks, then requires the exact
set of application logical names and their declared media types. Rehashing an
index cannot rename, omit or add an application resource, change its media type,
or replace declaration membership by changing its origin. The manifest is decoded
once; verification opens no host files. Dependency-only indexes without a bound
manifest keep their existing lock-only verification path.

Application selections also require the actual captured inventory bytes through
`source_inventory`. Before decoding, the bytes must match the external source
digest and index binding within the maintained source-inventory read limit of
4 MiB. The inventory is bounded at the existing 4096 captured-source entry limit.
Its manifest entry must contain the exact manifest digest and size. Every
declared source path must contain the exact digest and integer byte size of its
resource object; renamed inventory entries, changed bytes and malformed selected
metadata are refused. The inventory is decoded once, with no host path lookup.
Declared-empty selections still bind their manifest entry. Dependency-only
selections without a manifest do not need or parse an application inventory.

The shared six-language package assembler performs this verification before
writing resource layers. Changed source bytes at the same path cannot produce a
resource package against a stale captured inventory. Equal and empty bytes keep
their existing object and stream mappings; unselected source files stay absent
from the resource inventory.

These are membership proofs within externally bound captured inputs. The caller
still authenticates source, component and graph identities and signatures; the
ordinary compiler observation and signed package retain their roles. Verification
does not reconstruct original source files or establish that a component executes
a language's runtime resource API. Manifest source paths are never resolved
against a host filesystem by verification.

Verification of a dependency-origin row also requires the actual reviewed lock
bytes through the explicit `dependency_lock` input, bounded at 8 MiB. The bytes
must match the externally supplied lock digest and the index binding before the
lock is decoded. Each owner must occur exactly once, with the resource's exact
digest and size in its captured file inventory; the verifier and capture use the
same membership checks. A digest alone, substituted lock, rehashed foreign owner
or unobserved payload cannot supply that proof. The lock is parsed once per
verification, without reading a host path or fetching dependencies. Application
rows do not require dependency-lock bytes. This verifies membership within the
bound lock; the caller must still authenticate the captured graph and the source,
component and lock digests, and the ordinary signed package authenticates the
selected index. It does not qualify a language's runtime resource API.

A matching dependency file record must use an integer byte size. Boolean and
floating-point values cannot authenticate empty or one-byte resources merely
because their numeric equality matches the payload length. Capture and index
verification apply the same rule, including after a lock/index rehash. Valid
integer sizes and unselected records retain their existing behavior; this local
membership check does not replace validation or authentication of the full graph.

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
| C | Captured constant data; explicit [C23 `#embed`](c-compiled-resources.md) and declared dependency resource objects | Signed C23 exact bytes/aliases/empty/missing and trap/fuel fresh-state controls; no runtime filesystem lookup |
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

The maintained scratch-refusal packet is separate from immutable-resource
lookup. `tools/qualify_sdk_scratch.py` consumes that language's exact passed normal
qualification, native five and four unchanged companion packages; it builds one
new ordinary greeting component and uses the original signing/admission/node
pipeline. Its default-off runner selector adds entry, open, create, temporary
file/directory, explicit fixture-trap and fresh-state calls. Every successful
refusal must be caught by the actual standard API, preserve original budgets,
produce no external effects and retire physical/provider owners. A later close or
write error cannot disguise an already successful open/create. The packet grants
no filesystem or scratch provider and preserves required existing runtime grants.

The source fixtures use `std::fs`, libc `fopen`/`tmpfile`, Go `os` file APIs, Java
`java.io` and .NET `System.IO`. Rust has no standard temporary-file factory, so its
third case is a relative temporary-directory creation attempt. C compiler imports
must still satisfy the maintained closed profile: a componentization failure is
retained as failure and cannot be counted as a caught runtime Unsupported error.
`NotFound`, access denial and general I/O categories remain distinct from concrete
Unsupported; neither a generic trap nor a successful compiler build proves API
support or refusal. Source controls currently pass; signed five-language results
are pending and no whole criterion is complete.

ECMAScript has no standard filesystem API. The corresponding TypeScript packet
(`tools/qualify_typescript_scratch_refusals.py`) captures an outside npm module,
removes its originals and invokes the real isolated compiler for reachable
`node:fs` open/create/temp operations. Only the exact uninstalled-standard-module
bundle diagnostic counts. This is compiler-refusal evidence, not a claim that a
Node filesystem facade executes in the component. The owning language receipts
feed the existing SDK conformance work in #694; this adds no cross-language gate.

Related: [captured dependencies](application-dependencies.md),
[compatibility reports](library-compatibility.md), and
[guest SDK development](guest-sdk.md).
