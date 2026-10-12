# PR #856: current .NET resource and clock reconciliation

The original `ccb449a91f9a82c7373c43b89488279ec9e64b71` checkpoint owns the
.NET slice of #681, with #693 and #679 compatibility boundaries. The issue
bodies and comments were reviewed. Its compiler is reconciled with the captured
input, approved generator and transaction owners delivered through #843/#956,
and the current completion fixes from #851/#852. The bounded HTTP peer is
retained through #912 rather than restoring the older GET/HEAD body restriction.

One exact validated resource selection now supplies both immutable package
layers and ordinary `Assembly.GetManifestResourceStream` inputs. Logical names
remain literal through MSBuild; content-addressed bytes, alias/count/byte limits,
captured dependency ownership and post-compilation rechecks remain enforced.
No filesystem or scratch authority is introduced. A signed greeting fixture
checks binary, empty, duplicate-content, culture-like and literal logical names,
independent stream positions, absent lookup and disposal, with eight repetitions.

The separate wall-clock adapter is selected only when authoritative WIT declares
the exact `latent:clock/wall@0.1.0` dependency and NativeAOT actually imports the
corresponding WASI clock. Composition replaces only the closed clock export;
all other duplicate interfaces remain rejected. Milliseconds are divided before
nanosecond conversion, preserving full-width unsigned input without overflow.
This grants neither timers nor ambient WASI access.

The actual compiled wall component also passed five private Wasmtime 48.0.5
controls for 0, 1, 999, 1,000 and the maximum unsigned 64-bit millisecond value.
Each fresh instance called its explicitly installed test clock exactly once.
Missing and wrong-version host imports were refused. A separate 1 MiB control
refused the component's 17-page initial memory before a guest call; the positive
probe used an explicit 2 MiB ceiling and 100,000 fuel. Component and probe bytes
were frozen and rechecked around execution. The
[source and component identities](../../../testing/evidence/dotnet-wall-component-control-2026-10-12.json)
retain those boundaries. This checks actual adapter conversion independently
of managed guest execution.

A separate freshly built and signed resource guest executed ordinary
`DateTime.UtcNow` through the real node and returned ticks inside the host's
observed interval. Removing only its wall grant, while retaining its monotonic
and noncrypto grants, refused preparation with zero guest fuel and memory.
The original resource helper and all 27 maintained tutorial/fault/HTTP
invocations passed. Its
[exact authored source, world and native identities](../../../testing/evidence/dotnet-utc-resource-control-2026-10-12.json)
remain bound to that private ephemeral signing fixture. The two failed private
configuration attempts are retained separately. This is focused signed guest
evidence; production distribution and the whole SDK clock matrix remain open.

The expanded source suite passed 154 cases on Linux. The additional signed
fixture selection control passed on Windows. Pinned .NET SDK 10.0.100 compiled
and executed the standard resource lookup profile, including independent stream
positions and disposal. That receipt explicitly records `nativeAotGuest=false`
and `signedInvocations=0`. The maintained NativeAOT tools and all five runtime
adapters, including wall clock, compiled successfully. Current command coverage
retains 88 baseline and 280 required run blocks with 149 delegated owners.

The ordinary resource helper compiled through NativeAOT, was signed/admitted on
the real node and passed all original authoring tutorial/fault/HTTP controls.
Its CLR string hashing requires the existing explicit noncrypto entropy port;
without that declaration the first private attempt trapped. The passing attempt
kept the original resource helper and added only the authoritative declaration
and its finite fixture provider/grant. Missing entropy authority was denied
before execution with zero fuel and memory. The original failure and subsequent
diagnostic build failures remain in private evidence. Resource data itself
introduces no authority, and secure random remains denied.

The host MSBuild receipt is separate from this signed guest evidence. Full six-language #681 acceptance,
the .NET thread-pool port #746 and independent runtime gates remain open. This
PR does not close a ticket.
