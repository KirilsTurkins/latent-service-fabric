# Captured C23 resources

The C builder can select C23 explicitly in `capsule-project.json`:

```json
{"languageStandard": "c23"}
```

Add this field to the existing project document; the other required project
fields remain required. Omitted selection keeps C11. If a reviewed application
dependency selection declares `languageStandard`, it must match the project.
Resolve and review changed dependency inputs before building.

This selection uses the pinned Zig compiler's standard `#embed` preprocessing.
An ordinary C source or captured library can embed exact UTF-8, binary and empty
files without a language-specific resource API:

```c
static const unsigned char bytes[] = {
#embed "payload.bin"
};
static const unsigned char text[] = {
#embed "message.txt" suffix(,0)
};
static const unsigned char empty[] = {
#embed "empty.bin" if_empty(0)
};
#if __has_embed("missing.bin") == __STDC_EMBED_NOT_FOUND__
/* Explicit missing-data behavior belongs to the ordinary application. */
#endif
```

`suffix(,0)` adds the string terminator in compiled C data; the captured and
packaged resource bytes keep their original length. `if_empty(0)` supplies one
sentinel element in the C array without changing the empty resource object.
Repeated references to the same bytes share one package object. Binary bytes
are never decoded or rewritten. Missing inputs needed by `#embed` fail ordinary
preprocessing; `__has_embed` provides the standard explicit presence check.

Declare package membership separately. A normal captured dependency artifact
with `role: "resource"` can use this metadata:

```json
{
  "resources": [
    {"path": "data/payload.bin", "source": "payload.bin", "mediaType": "application/octet-stream"},
    {"path": "data/message.txt", "source": "message.txt", "mediaType": "text/plain"}
  ]
}
```

Each `source` is relative to that artifact's captured inventory. A source
library can depend on the resource artifact using its normal captured graph
edge. Explicit single-file artifacts can also use `logicalPath` and `mediaType`;
their one original file is retained exactly, including existing C include
fragments. Undeclared resource files do not become package assets.

The builder selects bytes only from the reviewed lock, captured store and
materialized dependency inputs. Digest, integer size, original lock bytes and
artifact membership must agree. The [shared resource profile](packaged-resources.md)
then checks combined application/dependency names, collisions and byte limits.
It writes the unchanged `resource-index.json` and content-addressed objects;
the source, component, dependency lock and ordinary package identities bind
those outputs. This is captured-input membership, not independent source
signature authentication.

For C23, declared resource artifact roots become bounded `--embed-dir=<directory>` search
roots, at most 64. Both compilation and the preprocessor dependency observation
receive the same standard and roots. The compiler records the actual files it
reads, including embedded files. Normal C11 builds and existing static archive
ABI validation keep their existing behavior. The explicit language selection
does not make an archive compiled under another profile compatible.

This is immutable compiled data. It installs no writable scratch directory,
runtime filesystem, resource stream, provider, grant, background thread or
process environment. Ordinary runtime filesystem lookup remains unsupported
by this profile. Compiler isolation and final component inspection still reject
ambient host access; resource selection supplies no runtime authority.

## Finite qualification

The owning C workflow preserves the original clock/entropy, stdio and combined
campaigns and adds this separate command on their exact ordinary native tuple:

```bash
python3 tools/qualify_c_standard_facilities.py --compiled-resources \
  --native-directory "$NATIVE" --native-tuple "$NATIVE/native-tuple.json" \
  --zig "$C_TOOLS/zig/zig" --wit-bindgen "$C_TOOLS/wit-bindgen" \
  --wasm-tools "$C_TOOLS/wasm-tools" --output /tmp/c-compiled-resources
```

The programme captures an outside source library with a transitive raw-resource
artifact, deletes both original directories, and builds the five existing C
controls. It verifies four logical resources and three exact objects, including
empty bytes and a shared binary object, against the reviewed lock and observed
preprocessor inputs. Six signed calls must return distinct UTF-8, binary,
empty, shared, missing and fresh-state results. A guest trap and original fuel
exhaustion must each retire their physical activation owners before a fresh
resource call. These ten calls are additional to the original 27 authoring,
fault and peer outcomes. Original deadlines, limits, cleanup and signed
admission remain required.

Focused source tests cover projection and command/ownership guard wiring.
**The new C23 compiled-component and signed-node campaign is pending.** Earlier
individual and combined facility receipts retain their original scope and do
not qualify this new path. C concurrency, writable scratch and complete
six-language resource/facility acceptance in issue #681 remain open.

Related: [C authoring](c-authoring.md), [captured dependencies](application-dependencies.md),
and [standard C facilities](c-standard-facilities.md).
