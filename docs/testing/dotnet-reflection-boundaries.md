# .NET unsupported reflection and catalogue-free build qualification

Issue #687 already has actual signed evidence for descriptor-rooted method lookup
and invocation, caught `Assembly.Load` refusal, a separate uncaught trap and fresh
success. This additional programme retains those four cases and adds three:

- An ordinary outside library calls the real `DynamicMethod` constructor after
  verifying both dynamic-code runtime feature flags are false. Only
  `PlatformNotSupportedException` yields the expected fixed result.
- A descriptor roots a public parameterless method returning `ReadOnlySpan<int>`.
  Its metadata must report a byref-like return. `MethodInfo.Invoke` must refuse
  with `NotSupportedException` before its body increments an owned counter.
- A fresh activation performs the original supported rooted reflection again.

These operations use the selected NativeAOT CoreLib, rather than an SDK facade
that pretends to implement reflection or JIT. The maintained library, local NuGet
capture, exact review, embedded original assembly and removal of originals are
unchanged in the default mode. `dotnet_reflection_boundaries` is explicit,
strictly boolean, .NET-only and incompatible with the other dependency probes.
The full normal node programme remains mandatory, followed by all seven cases.
The signed target revision, zero outbound requests and physical reaping are
checked. A generic guest trap is not relabelled as a specific runtime cause.

The second required boundary is a build without optional catalogue or reference
data. There is no dependency eligibility catalogue to delete in the current
repository. `dotnet_catalogue_free_build.py` instead copies only the maintained
build recipe, its static Python import support, and the exact maintained host ABI
and transaction seed JSON. It does not copy documentation, reference databases,
Git metadata, project originals or a package-eligibility list. The ordinary
application still contains its captured SDK, locks, source and accepted NuGet CAS
objects; those remain required compiler inputs.

The staged entry runs in isolated Python with site initialization disabled. It
calls the unchanged ordinary builder with `offline=True`. Its input inventory is
pinned before launch and rechecked afterwards; the actual build recipe must be
contained in that inventory. Source count, byte and per-file limits are finite;
links, hardlinks, escapes, missing recipe inputs, extra data and substituted
source refuse. The compiler remains network-denied and receives no credentials.
No machine trust, compiler recipe or runtime authority is relaxed.

Run the maintained programme after the ordinary dependency qualification:

```console
python3 tools/qualify_dotnet_reflection_boundaries.py --prepared-qualification /owned/dotnet-capsule-dependencies --output /owned/reflection-boundaries --tools /owned/dotnet-authoring-tools
```

The original .NET workflow commands and 75-minute job bound are retained. The new
steps add focused Python controls and one captured library/component build,
ordinary demo signing and a signed 34-call node programme. Public receipts retain
bounded relative source identities, selected descriptor/resource materials,
actual recipe and component identities, the seven case results and clean/reaped
shutdown. Private source payloads and signing keys are not added to uploads.

The focused Python controls exercise real project selection, static source
staging/import, compiler/descriptor consumers and mocked node boundaries. They do
not execute NativeAOT or prove the two unsupported operations on a component.
Only an actual successful owning hosted receipt establishes that evidence. No
complete reflection, JIT, reproducible-build, hermetic-build or whole-ticket
qualification is claimed by source tests or by the staged-source receipt.
