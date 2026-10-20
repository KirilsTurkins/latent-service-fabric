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

These are actual IL/metadata and focused reference-chain controls. Fresh
NativeAOT compilation, preserved invalid-argument results, signed reached/caught
Unsupported results and physical retirement remain mandatory owning gates.
No guest execution pass, writable scratch implementation, whole criterion or
whole-ticket completion is claimed by this source milestone.
