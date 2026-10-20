# Immutable packaged resources

Declare immutable files in `capsule-resources.json`. The six maintained builders
use the same exact-byte package assembler. It reads captured project files and
selected dependency resources; it never reads a new host path during assembly.
Application declarations are validated at source capture, before language
resolution, contracts tools or compiler execution. The C builder performs the
same preflight immediately after its separate source capture. Missing bytes,
unsafe paths, collisions and count/aggregate exhaustion retain their distinct
static categories. Dependency-owned additions are still checked after their
reviewed closure is available, and full package/member verification still runs
before writing resource layers. Source capture may impose stricter file limits
than the resource profile's upper bounds.

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

| Language | Selected standard data path | Actual finite component evidence | Remaining API boundary |
| --- | --- | --- | --- |
| Rust | Captured `include_bytes!` / `include_str!` data, including transitive UTF-8/binary inputs | [Signed outside/transitive resource and entropy programme](../testing/evidence/rust-standard-entropy-signed-2026-10-20.json) | Compile-time inclusion does not provide runtime filesystem lookup |
| C | Captured constants and explicit [C23 `#embed`](c-compiled-resources.md) with declared dependency resource objects | [C23 exact UTF-8/binary/empty/alias/missing and trap/fuel/fresh controls](../testing/evidence/c23-resources-passed-2026-10-19.json) | No general runtime filesystem or resource-stream facade |
| TypeScript | Static ESM imports of captured `.txt` and `.bin` assets through a transitive package | [Signed clock library's exact text/binary data checks](../testing/evidence/typescript-standard-clocks-signed-2026-10-20.json) | Dynamic asset lookup, arbitrary extensions and a Node filesystem are outside these observations |
| Go | Captured `//go:embed` string data in a transitive module | [Signed outside entropy library's exact embedded UTF-8 checks](../testing/evidence/go-standard-entropy-signed-2026-10-19.json) | This string path does not qualify every `embed.FS` lookup, missing file or independent stream handle |
| Java | Selected immutable classpath bytes through `Class.getResourceAsStream` and direct `ClassLoader.getResourceAsStream` | [Signed two-library class resource observation](../testing/evidence/java-two-library-resource-node-2026-10-02.json) and [direct ClassLoader owning job](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/39174038239/job/117813178316) | Other resource APIs and general filesystem lookup need separate evidence |
| .NET | One verified selection supplies package layers and embedded compiler inputs; `Assembly.GetManifestResourceStream` | [Signed binary/empty/literal/missing/position/disposal controls](../testing/evidence/dotnet-utc-resource-control-2026-10-12.json) | Broader resource APIs, NuGet distribution and concurrent stream lifecycle need their own qualification |

The [.NET resource and explicit wall-clock reconciliation](https://github.com/KirilsTurkins/latent-service-fabric/blob/200c17c26b24d6bf06d8d28102362ea714c1f4eb/docs/development/phase4-handoffs/2026-10-12/pr856-reconciliation.md)
records fresh signed-node checks for binary/empty resources, literal names,
independent stream positions, absent lookup and disposal. Those checks do not
qualify every NuGet library or a new packaged toolkit. Java's direct ClassLoader
selection also has an [exact-head post-merge reconciliation](https://github.com/KirilsTurkins/latent-service-fabric/issues/681#issuecomment-6256601737).
Other Java lookup APIs remain outside that finite evidence.

Each linked observation keeps its tested source, component, compiler and native
identities. Publishing this matrix does not reclassify an old host as a build of
current development. The TypeScript and Go rows now name the exact executed
static-import/embedded-string paths instead of treating those paths as wholly
unexecuted; neither row advertises a general dynamic lookup API.

This table identifies the ingestion paths and their runtime acceptance boundaries;
package assembly alone does not prove those APIs execute. The index records
`runtimeLookup: language-profile-qualification-required`. Each language owner
must qualify the unchanged standard API in a signed admitted component, including
transitive data, outside-checkout/offline and lifecycle cases, before advertising
that path as supported. The linked finite observations supply the named paths'
existing execution evidence; they do not complete the whole six-language matrix.
A runtime lookup cannot resolve dependencies or fall back to the host filesystem.

The remaining [#681](https://github.com/KirilsTurkins/latent-service-fabric/issues/681)
matrix includes every selected API's missing/denied/malformed/exhausted outcomes,
all-six compiler collision/traversal/limit/tamper controls, and resource/log
callbacks under each corresponding runtime's concurrent reads, root cancellation,
pending flush, trap, late completion and fresh cross-tenant reuse. The scalar
resource, logging, clock and entropy observations retain their separate scopes;
stream close/disposal alone is not evidence that a host owner retired. These
remaining rows feed [#694](https://github.com/KirilsTurkins/latent-service-fabric/issues/694).

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
support or refusal. Source controls pass; the language-specific actual results
below retain their distinct boundaries and no whole criterion is complete. The Rust workflow has a separate
20-minute child consuming an exact normal public bundle; the original 35-minute
parent and all its commands remain mandatory. The C workflow also has a separate
20-minute child using only its exact normal public products and pinned
Zig/bindgen/wasm-tools. A default-false manual `qualify-scratch-refusals` selection
runs the original 35-minute runtime job and this child, skipping only the
separate unchanged 25-minute standard-facility campaign on that explicit manual
selection. PR, push and default manual runs retain every original job, command
and deadline. Other language execution
wiring retains its own pending boundary. The .NET workflow adds a separate
20-minute child of its unchanged75-minute normal parent. It authenticates only
the public normal products, builds one fresh NativeAOT component and runs the
six filesystem/refusal/trap/fresh-state calls without adding entropy or file
authority. The corrected .NET
[run39355824576/job118410242354](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/39355824576/job/118410242354)
passed33 invocations at source488b264e9b with clean retirement, but its open and
create calls caught `DirectoryNotFoundException` and its temporary-file call
caught `IOException`. Those results remain unresolved behavior for criterion5,
not concrete Unsupported. The earlier entropy-specific harness failure remains
separate. The compiler-owned [closed CoreLib filesystem boundary](dotnet-closed-filesystem.md)
now has exact-source derivation and reference-chain controls; its fresh pure/joined
NativeAOT and signed argument/Unsupported gates remain pending. Rust results are recorded below. Actual results also project into the existing
source/component-bound compatibility report: only precise Unsupported is
`unsupported-reached`; NotFound, other errors and the deliberate fixture trap
remain unresolved observations.

The corrected Rust parent passed at source38fedd53bb in
[job118418832964](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/39358494292/job/118418832964).
Its scratch child then failed during offline compilation: the workspace fetch
had not downloaded the owned fixture lock's `cpufeatures0.2.17`. No scratch guest
ran. The qualifier now performs a bounded data-only `cargo fetch --locked`
against that fixture's manifest, verifies its complete source inventory is
unchanged, and retains the subsequent build's offline requirement. The first
replay at de9eb70c30 then retained a second compile failure for `addr2line0.26.1`: `--target`
filtered native rows out of that lock download. The corrected fetch has no target
filter, so it acquires the whole exact lock without executing its packages. The separate
default-false `replay-scratch-refusals` lane authenticates the passed38 public
bundle, native five and four companions, then builds/signs one fresh component
and requires the original27 plus six calls. Its 20-minute limit and the original
nine job bodies are preserved. The original native source stays historical38;
no normal receipt is rebound to later host changes.

The corrected [run39366052154/job118443039897](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/39366052154/job/118443039897)
at source669fbc56f1 passed the whole targeted job: data-only whole-lock fetch,
fresh offline component build, normal packaging/signing/admission and all33
known/reaped invocations. Ordinary `File::open`, `OpenOptions::open` and
`create_dir` each caught `ErrorKind::Unsupported`. All12 provider-idle samples
had zero active owners,30 physical samples were retained, and shutdown was
clean. The [source-bound observation](../testing/evidence/rust-scratch-signed-2026-10-20.json)
retains both earlier compile failures separately; this finite Rust result does
not complete the six-language scratch or whole resource/facility criterion.
The first C scratch child failed during actual compilation, before signing or
invocation: [job118415549455](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/39354843145/job/118415549455)
retained Zig0.16's deprecated `tmpfile` diagnostic under the unchanged `-Werror`.
That failure is not a caught Unsupported result. The compiler-owned
`c-closed-filesystem-stdio-v1` overlay now keeps the original libc declarations
via `include_next`, then maps ordinary WASI `fopen` and `tmpfile` to null with
`ENOTSUP`. The original `fopen` initial-mode `EINVAL` check remains ahead of
the closed refusal. Other stdio operations and non-WASI includes are unchanged;
no file descriptor, filesystem import or writable storage is supplied.

Compiler admission authenticates the exact Zig0.16 selected stdio header and
WASI libc `fopen` source, plus the captured overlay, and rechecks all three
materials after compilation. The two upstream preimages come from the
[pinned Zig source](https://codeberg.org/ziglang/zig/src/tag/0.16.0/lib/libc/wasi/libc-top-half/musl/src/stdio/fopen.c).
The overlay is part of normal SDK capture and recipe identity; no application
call is rewritten and no warning is disabled. Six new focused controls pass,
including source drift refusal and normal compiler admission; the previous
compiler fails the new required-material control.

The [actual signed replay](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/39362851384/job/118432795119)
at source6578570a34 compiled the fresh component and passed all33 known/reaped
invocations, including three caught `errno=notsup` results, explicit fixture
trap and fresh state. All12 provider-idle samples had zero active owners,
30 physical samples were retained, and node shutdown was clean. The job then
failed solely while projecting the C operation labels into the compatibility
report: parentheses were outside its existing closed token grammar. The labels
now use `fopen/read` and `fopen/create`; the grammar is unchanged. An independent
[authenticated artifact reprojection](../testing/evidence/c-closed-filesystem-signed-2026-10-20.json)
verifies the component, source, three port materials and all33 outcomes. It
records the original job's failure separately from the passing runtime programme
and corrected report projection. No compilation or signed invocation was
repeated for this label correction. The original passed27-call parent/native
products remain historical29b, separate from the changed compiler and fresh
component; the normal prepared verifier is unchanged.

ECMAScript has no standard filesystem API. The corresponding TypeScript packet
(`tools/qualify_typescript_scratch_refusals.py`) captures an outside npm module,
removes its originals and invokes the real isolated compiler for reachable
`node:fs` open/create/temp operations. Only the exact uninstalled-standard-module
bundle diagnostic counts. This is compiler-refusal evidence, not a claim that a
Node filesystem facade executes in the component. A default-false `qualify-scratch-refusals`
selection in the registered TypeScript workflow runs only these three compiler
refusals under a separate 20-minute job, reusing authenticated historical public
contracts/packager tools; it performs no native rebuild or node invocation.
Its current compiler receipt and original compiled-source ancestry remain separate.
[Actual three-case qualification](../testing/evidence/typescript-scratch-refusals-2026-10-20.json)
passed at source99eaccd694 in run39350623578/job118393691728: all three outside
packages were captured/reviewed, originals removed and the actual compiler
completed with the exact uninstalled-module refusal. All112 compiler materials
remain exact after composition. This executes no node and qualifies no native
filesystem result; the native-language programmes remain separately pending.
The Java workflow also exports its exact passed normal public products, then
runs one fresh Java component in a separate 20-minute scratch child. The original
55-minute parent steps and deadline remain intact. The default-false manual
`qualify-scratch-refusals` selector skips only the unrelated dependency-ingestion
matrix; normal PR/manual runs retain it. The child uses the same pinned JDK,
Gradle, WASI SDK and bindings, with no Rust setup or native-host build. It retains
every caught category and compatibility-report finding: a Java FileNotFound or
generic I/O error is unresolved behavior, not a reached Unsupported result.
This source wiring has focused controls; actual Java scratch outcomes remain
pending. It grants no filesystem provider or scratch storage.
The owning language receipts
feed the existing SDK conformance work in #694; this adds no cross-language gate.

Related: [captured dependencies](application-dependencies.md),
[compatibility reports](library-compatibility.md), and
[guest SDK development](guest-sdk.md).
