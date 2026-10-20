# .NET closed filesystem boundary

The maintained guest has no ambient filesystem or writable scratch authority.
The prior [signed scratch run](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/39355824576/job/118410242354)
passed its33 invocations, but `File.OpenRead` and `File.Open` caught
`DirectoryNotFoundException`, while `Path.GetTempFileName` caught `IOException`.
Those actual results are retained as unresolved behavior; they do not establish
the concrete Unsupported alternative in issue #681 criterion5.

The compiler-owned `dotnet-closed-filesystem-v1` derivation replaces only the
managed `Interop.Sys.Open` and `Interop.Sys.MksTemps` bodies in the exact pinned
WASI CoreLib. They throw `PlatformNotSupportedException`. The application and
public BCL methods are unchanged. Ordinary `FileStream` enum/access/share/buffer
checks and `Path.GetFullPath` remain ahead of `Open`. No filesystem import,
provider, handle or application shim is added. This is a boundary for the named
open/create/temporary-file operations, not a claim that every filesystem query
returns Unsupported.

Selection does not require CLOCK, HTTP or ACTIVATION declarations. A pure
closed component derives the original CoreLib directly. When the explicit
TaskWait profile is selected, its original derived assembly remains immutable
and rechecked; a second private copy applies the two filesystem changes.
Separate MSBuild targets bind that final copy after TaskWait selection. The
TaskWait, HTTP and filesystem observations verify the same actual ILC response
and final CoreLib reference, while retaining the intermediate TaskWait digest.
Unknown, missing, duplicated or original/intermediate final references fail
closed. Existing entropy and other assembly transformations remain separate.

The [actual metadata derivation](../testing/evidence/dotnet-closed-filesystem-derivation-2026-10-20.json)
uses the pinned5,694,976-byte CoreLib member, SHA256
`29e4bd3f70bfb0e0ea00fb2511e28ee9832b56caf9ddb5cd60906fe3bcaad735`,
and pinned Mono.Cecil. The member digest is verified; this audit does not claim
verification of the entire downloaded NuGet archive. The pure derivation keeps
44,744 other method bodies unchanged. The joined derivation keeps the exact
`75e20677...` TaskWait intermediate and44,753 other base method bodies unchanged.
Serialized output is reopened and checked before each receipt is issued.

The [first actual focused run](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/39371941107/job/118461535088)
compiled both components with NativeAOT. The pure component passed all39
outcomes, including three caught `PlatformNotSupportedException` results, six
original argument errors,18 zero-active-owner samples,36 physical samples and
clean shutdown. The [bounded observation](../testing/evidence/dotnet-closed-filesystem-pure-signed-2026-10-20.json)
binds both component/build identities and the unchanged current application
inventories to that artifact. The joined component was rejected before entry with
`incompatible-contract`: the test configured CLOCK but omitted the declared
ACTIVATION provider. That failed run remains a failure, not a joined pass.

The owning20-minute scratch child preserves its normal pure-component command,
then adds a joined TaskWait component. Each programme retains the original27
SDK outcomes, the six filesystem/trap/fresh calls, and six named null, empty,
NUL-path, invalid-mode, invalid-access and incompatible-mode/access cases.
The pure component has no ACTIVATION grant. A separate default-off joined
selector configures only its declared ACTIVATION provider, with the original
task limits and policy ceilings. After the original CLOCK denial, a separate
missing-ACTIVATION invocation must be denied before guest entry with zero
consumption; only then is the ACTIVATION grant installed for the greeting.
No WALL, RANDOM, HTTP or filesystem authority is added. The six argument results must retain their exact
`ArgumentNullException`, `ArgumentException` or `ArgumentOutOfRangeException`
categories. Unsupported, a generic trap or an unknown error cannot satisfy
those controls. Both phases must retain zero active owners, clean shutdown and
the exact final CoreLib reference chain. Pure39 plus joined40 (one additional
authority denial) make79 required outcomes; the joined40 remain pending.
This finite proof does not establish writable scratch, every filesystem query,
the whole criterion or whole-ticket completion.
