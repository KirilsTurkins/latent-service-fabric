# Captured .NET reflection qualification

This programme advances the supported descriptor and concrete dynamic-loading
boundaries of [issue #687](https://github.com/KirilsTurkins/latent-service-fabric/issues/687).
It preserves the ordinary application, compiler, WIT, signing and admission
paths. It does not supply a complete CLR, JIT or arbitrary reflection promise.

`tools/qualify_dotnet_reflection.py` first verifies the preceding captured NuGet
qualification's exact source inventory, five native products and four companion
builds. It compiles one ordinary developer library with the pinned captured
compiler and places its original DLL in a fresh local NuGet package. Normal
add, native resolve, exact candidate review and dependency verification capture
that package. Its source, feed, preparation tools and archive are removed before
the application is compiled offline.

The application selects a literal `TrimmerRootDescriptor`. The descriptor roots
`OutsideReflectionRoot.ReflectValue` in `ReflectionInput`; the member is reached
through runtime-supplied type and method names using ordinary
`Assembly.GetType`, `Type.GetMethod` and `MethodInfo.Invoke`. No annotation stub,
warning suppression, replacement reflection method or additional runtime grant
is introduced. The qualification checks the descriptor's exact digest and size
in source inputs, actual compiler selection and the build observation's bound
material before ordinary package signing.
The same actual compiled DLL is also selected as an embedded resource, bound
through its own source/compiler identities, and supplied to the dynamic-load
negative. That call uses captured valid managed bytes, rather than malformed
placeholder bytes or an unavailable original filesystem path.

The enforced node programme requires four independently retired invocations:

1. Descriptor-selected reflection returns its exact value.
2. `Assembly.Load(byte[])` is caught specifically as
   `PlatformNotSupportedException`, with an explicit fallback value.
3. The same unsupported operation is uncaught and ends in a certain terminal
   guest trap. Resource exhaustion, uncertainty and an unreaped process fail.
4. A fresh invocation again returns the exact reflected value; the external
   library checks that activation-local static call state starts empty.

Every observation binds the actual global route snapshot, selected revision,
component digest and intended publication, rather than comparing the route's
generation to a deployment object's generation. Existing ownership samples and
provider-idle checks run between calls. A generic terminal trap does not itself
identify its underlying exception; the caught call is separate evidence.

The upstream [.NET 10 NativeAOT assembly loader](https://github.com/dotnet/runtime/blob/v10.0.0/src/coreclr/nativeaot/System.Private.CoreLib/src/System/Runtime/Loader/AssemblyLoadContext.NativeAot.cs)
rejects nonempty in-memory dynamic loads with `PlatformNotSupportedException`.
That source expectation is not a substitute for the selected compiler's actual
component result. Only a successful exact-source hosted receipt establishes
this finite supported/refused matrix.

The pure Python controls exercise the real descriptor declaration and preimage
consumer, normal producer boundaries, forged source/compiler/material evidence,
strict selector, revision mismatch, failure classification and observer error
preservation. They do not execute C#, NativeAOT or a component. The additional
hosted step reuses the existing prepared products and 75-minute job limit;
it does not rerun SDK preparation or increase invocation budgets.

Public retention contains fixed JSON inventories and results, without raw
compiler streams or arbitrary workspace archives. Receipts explicitly retain
`fullTicketQualification: false`, `hermetic: false`, `cleanHost: false` and
`publisherAuthenticated: false`. Authenticated private-feed lifecycle, the
remaining #687 matrix and whole-ticket closure are separate requirements.
