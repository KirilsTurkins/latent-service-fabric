# Captured NuGet application inputs

Use `dotnet_capsule.py add PROJECT PACKAGE --version EXACT_VERSION` to add an ordinary `PackageReference` to the application's `Capsule.csproj`. Keep the maintained SDK properties, WIT items, compiler package lock and `vendor/lsf` unchanged. Package identities describe provenance and do not require an LSF catalogue entry.

Resolve into a fresh review candidate, accept its exact lock, and compile offline:

```powershell
python tools/dotnet_capsule.py add ./my-csharp MemoryPack --version 1.21.4
python tools/dotnet_capsule.py resolve ./my-csharp --candidate ./nuget-candidate.json --dotnet ./reviewed-dotnet/dotnet --tools ./reviewed-native-aot
$candidate = 'sha256:' + (Get-FileHash -LiteralPath ./nuget-candidate.json -Algorithm SHA256).Hash.ToLowerInvariant()
python tools/dotnet_capsule.py review-lock ./my-csharp --candidate ./nuget-candidate.json --expect $candidate
python tools/dotnet_capsule.py dependencies ./my-csharp
python tools/dotnet_capsule.py build ./my-csharp --tools ./reviewed-native-aot --output ./my-csharp/target/build-1 --repository https://github.com/example/application
```

MemoryPack includes an executable source generator. Its first build stops with the exact approval request described below; inspect and explicitly approve that request on a fresh build attempt. Dependency review alone does not approve compiler execution.

The fetch stage uses .NET SDK 10.0.100, a fresh home/cache and an SDK-owned restore project. It evaluates only reviewed literal package, resource and trimming declarations. It never imports application targets, directory props, property functions or an application's generated `obj` inputs. Native NuGet selects versions, transitive edges and assets for `net10.0` and `wasi-wasm`; changing those targets requires an installed compiler/runtime profile. Conditions using these two target properties and literal equality/inequality are recorded. Package `IncludeAssets`, `ExcludeAssets` and `PrivateAssets` retain native semantics. Version conflicts remain native restore errors.

`packages.lock.json`, the normalized `nuget-resolved.lock.json`, original package archives and selected bytes are bound independently of the SDK's compiler lock. Signed NuGet content hashes use the pinned SDK's NuGet algorithm and signature-integrity check; the original ZIP's SHA-256 is a separate identity. Missing graph edges, changed content hashes, unsafe archives, mutated SDK packages and unobserved offline asset fallback fail explicitly. The compiler never uses an ambient NuGet cache or installs dependencies during a guest invocation.

Native lock and assets documents are limited to 16 MiB each. Duplicate JSON fields, malformed values and nonstandard numeric constants are rejected before graph selection, exact review or offline package-cache preparation; an ambiguous native document cannot silently replace a selected package or asset record.

Package names and coordinates are compared with their canonical case-insensitive
identities. Case aliases in one lock target, package table or dependency edge,
and multiple versions of one package within a selected assets target, fail with
`nuget-native-package-identity-ambiguous` before acceptance or offline cache
creation. Unique mixed casing remains valid, as do different versions selected
by separate framework/runtime targets. These checks do not require catalogue
membership or alter the SDK/compiler locks.

The reviewed composer is checksum-pinned WAC 0.10.1 and includes the [upstream imported-resource alias fix](https://github.com/bytecodealliance/wac/pull/205). The SDK's original bundled composer and selected composer have separate identities in `compiler-patches.json`; source, compiler selection, containment and package inputs bind the change. That fix does not supply missing runtime interfaces or methods. After NativeAOT succeeds, the build retains `native-aot-raw.wasm` (at most 64 MiB) and its WIT JSON (at most 4 MiB) before runtime selection. Profile rejection therefore preserves the actual output after the temporary workspace is retired. NuGet asset verification uses the project declarations independently of the authoritative WIT imports. Before composition, `closed-runtime-coverage.json` compares the actual NativeAOT and runtime-adapter WIT metadata and names missing interfaces, types and methods. Missing-member failures also retain a bounded compatibility report. Member presence remains a necessary check; WAC checks type signatures, final validation rejects residual WASI imports, and execution requires separate qualification.

Application builds with captures require Linux x86-64 and bubblewrap. The maintained NativeAOT distribution, BCL/reference assemblies, WASI SDK, closed runtime adapter, child tools, Python standard library and observed loader files are captured and rechecked. A fresh compiler-owned package cache receives only the exact SDK packages and verified application closure. Compilation runs with network, home and credentials unavailable; source and package inputs are read-only. A finite SDK-owned account entry supplies compiler identity without importing the host's account database. The compiler host uses invariant globalization and disabled diagnostics; the optional SDK LTTng provider remains hashed but its unavailable ABI is not enabled. Offline NuGet keeps signature verification enabled with the captured SDK's certificate bundles and offline revocation mode; it does not claim current online certificate revocation evidence. [NuGet's signature verification documentation](https://learn.microsoft.com/en-us/dotnet/core/tools/nuget-signed-package-verification) describes the SDK certificate bundles. These are compiler settings and do not grant application runtime behavior. Receipts target a trusted single-user build host and retain `hermetic: false`.

The loader uses the captured Python library directory for both dependency observation and compiler execution, including hosted CPython executables with an absolute RUNPATH. Its receipt binds the hashed distribution owner and relative directory, so a fresh output location preserves the exact approval identity. The [focused loader qualification](../testing/evidence/dotnet-captured-python-loader-2026-10-01.json) reproduces the CI rejection with its original executable and library, then executes those same bytes in the namespace after deleting the original-path library.

The maintained outside-library fixture builds its reviewed library from that
library's owned preparation tree. This keeps the selected sources visible when
application projects live in a sibling `projects/` directory and excludes the
application and enclosing output tree from the preparation namespace. The
[nested-workspace controls](../testing/evidence/dotnet-nested-library-namespace-2026-10-01.json)
retain the original missing-source failure, exercise source reads and ambient
read denials through bubblewrap, and pass all 48 namespace/NuGet source controls.
Actual managed and NativeAOT compilation requires separate qualification.

Use literal `EmbeddedResource Include="resources/prefix.txt" LogicalName="example.prefix"` declarations for captured application data. The maintained compiler preserves those bytes and ordinary managed assembly resource lookup. Resources inside captured managed package assemblies retain their assembly ownership. Embedding grants no host filesystem access. Resource names, bytes, selected package ownership and final component identity must remain consistent with signed package/resource evidence; inclusion alone does not establish every resource-reader implementation.

`TrimmerRootDescriptor` items must refer to captured literal paths. The actual NativeAOT compiler performs reflection/trimming analysis; unsupported JIT, dynamic loading, native/PInvoke assets and missing runtime members remain concrete incompatibilities. An assembly's managed PE header is a capture preflight, not proof of its complete AOT compatibility. `Task`, `ThreadPool` or timer references do not imply blanket package rejection and do not establish their execution: #746 owns those runtime ports, and #693 owns ordinary `HttpClient`.

The application-native asset restriction is checked by the same selected-graph
analysis during resolution, exact lock review, offline cache preparation and
the compiler's post-restore selection recheck. A selected `native` asset or
`runtimeTargets` entry with `assetType: native` fails with
`nuget-selected-native-asset-runtime-abi-unavailable`. A native file that is only
present in a package's inventory does not trigger this restriction. Exact
SDK/compiler-native inputs retain their separately reviewed ownership; this
check does not authorize new application native code. Selected asset metadata
must be an object; malformed metadata fails with the closed
`nuget-native-asset-metadata-invalid` diagnostic without exposing its contents.
This preflight does not prove reachability, P/Invoke method compatibility,
reflection support or actual component execution.

Package targets, analyzers, source generators and `.resx` processing are executable compiler inputs. A first build retains `executable-input-approval-request.json` and stops before running them. Review its exact original/selected hashes, source, compiler distribution, loader closure and namespace policy, then pass its retained identity with `--executable-approval` on a fresh build attempt. Any changed source, lock, recipe or compiler input invalidates approval. After the owned NativeAOT process exits, the build retains generated source under `executable-input-outputs/` with an exact approval/input/recipe/compiler binding in `executable-input-outputs.json`. Capture rejects unsafe paths, more than 8192 entries or more than 64 MiB of generated bytes. The receipt records whether the compiler command succeeded; partial output from a failed command remains diagnostic evidence. Capture precedes runtime inspection and composition, so later ABI failures preserve the generated source. A successful build rechecks both the original generated bytes and retained copy before binding the receipt into build materials. Arbitrary application MSBuild targets remain outside the reviewed recipe.

For additional local/private feeds, pass `--feed-config` with `{"sources":[{"name":"private","url":"https://feed.example.com/index.json","patterns":["Example.*"],"authorizationEnv":"LSF_PRIVATE_NUGET_AUTH","username":"token"}]}` or a local `path` containing only `.nupkg` files. Feed mappings preserve native package-source selection. Credentials enter only an owned fetch configuration; public fetch receipts retain endpoint/location digests. Offline compilation inherits neither credentials nor feed configuration. `update PROJECT PACKAGE --version EXACT_VERSION` and `remove PROJECT PACKAGE` edit only application package declarations. They preserve SDK packages and the accepted lock; unsupported conditional edits require explicit source review. Resolve with `--update-lock` after a change, inspect the fresh candidate and accept its exact digest with `review-lock`. An old accepted lock remains unusable with changed declarations.

Resolution holds a project-owned authoring lock and stages native restore locks, asset metadata and original archives privately. It rechecks sources, SDK, descriptor, resolver and hash helper before publication. Failed attempts preserve the accepted lock and roll back their own published native/manifest bytes while preserving concurrent user edits. A successful resolution remains a candidate until exact review; cache presence grants no trust. A frontend project stores the manifest, accepted lock and CAS at its outer project root, with native inputs bound to its selected application directory. An inner shadow capture is rejected.

For a maintained frontend project, `test PROJECT --workspace WORKSPACE --select TEST` and `watch PROJECT --workspace WORKSPACE --select TEST` verify the same reviewed closure before delegating to normal `dev test` and `dev up --watch`. These commands preserve operator grants, recipe trust, package signing and admission; a changed lock or recipe requires normal fresh trust. `--frontend` requires its exact `--frontend-sha256`, or the owner delegates through its maintained source controller. Uncertain remote mutations retain their original exit code and are never retried automatically. The source controls exercise command delegation and transactional failure boundaries; actual signed .NET watch/update qualification remains a separate required gate.

Selected usernames and passwords must be nonempty strings of at most 16384
characters. ASCII controls and characters that cannot form valid XML are
rejected before restore; ordinary XML escaping preserves valid credential values.

The required .NET CI qualifier selects MemoryPack 1.21.4 and an independent developer NuGet assembly absent from the catalogue. The ordinary application calls `MemoryPackSerializer.Serialize` and `Deserialize` on a `MemoryPackable` payload; native NuGet captures MemoryPack.Core and the actual MemoryPack.Generator executable. The developer assembly performs ordinary embedded-resource lookup. Its feed and source are removed after capture. The qualifier first verifies generator denial without approval, then explicitly approves its fresh exact request under the SDK fixture policy and checks the retained generated payload source. Normal application builds never approve their own requests. The resulting component must still pass the existing signing, admission and node execution checks. Exact-head successful receipts are required before claiming this generated serialization qualification. The earlier SmartFormat/Newtonsoft.Json/ZString fixture remains available as a retained failed composition control; its NativeAOT success does not establish runtime compatibility. Supported reflection, private-feed recovery/update/removal/watch, generic resource-index integration and additional runtime cleanup qualification remain open until their receipts pass. Source-only authoring remains available through the existing guide.



The optional `dotnet-hash-entropy-v1` port requires the application's authoritative
world to import `latent:random/random@0.1.0`, with its normal installed provider
and explicit operator grant. It redirects only the captured CLR's
`SystemNative_GetNonCryptographicallySecureRandomBytes`; the separate secure
entrypoint retains its existing denial. The [pinned native implementation](https://github.com/dotnet/runtimelab/blob/8449ba666dd991e495d8363d9852f18eb86a1aa1/src/native/libs/System.Native/pal_random.c)
and exact original archive/member hashes identify the upstream input. The private
C object calls WASI insecure entropy; a separate adapter supplies only the two
reviewed insecure interface versions from the declared LSF random capability.
It rejects oversized or wrong-length results and propagates unavailable entropy
as a failure. It creates no entropy provider, grant, fixed seed or cryptographic
random implementation.

Reinstall the source-bound tool distribution after this SDK change. The compiler
retains the original native preimage, private object, trusted target and actual
link-response binding in `noncrypto-entropy-port.json`. It separately preserves
`compiler-patches-preparation.json` and binds the completed `compiler-patches.json`
and generated object into final build materials. Coverage examines both selected
adapters, rejects duplicate exports, and still requires real WAC composition,
validation and the exact final declared graph. This source port and its derivation
checks do not qualify ordinary resource lookup or MemoryPack execution. Those
claims require a fresh signed node run with the unchanged application/library
sources, entropy denial controls, recovery and measured retirement.

The application-library qualifier explicitly adds that import before NuGet
capture. Its optional node configuration binds one normal random provider only
to the greeting service. After installing the existing clock grant, it requires
the still-missing entropy grant to fail with zero guest fuel, memory and effects.
It then binds the exact installed provider profile, configuration digest and
epoch, and grants only `bytes` for that service and publication: at most 16
operations, eight input bytes, 4096 output bytes and five seconds. Existing
authoring defaults and other languages keep their original grants. This setup
retains ordinary secure-random denial and records no random payload bytes.

When an additional adapter is selected, the compiler connects every actual WASI
import once by its complete interface name. It retains the bounded
`runtime-composition.wac` source and `runtime-composition.json` receipt and binds
both into build materials. The original raw component, inspected graphs and
selected adapters must match before and after the owned composer runs. The
reviewed WAC binary still checks actual signatures and resource identities;
application host imports pass through to normal admission and grants.

## Qualification and retained evidence

The captured MemoryPack generator and developer resource assembly have a
source-bound offline build, signed-node invocation and recovery record. The
original library and component identities remain in these receipts; they do
not qualify a new source build or a clean packaged distribution.

| Recorded boundary | Evidence |
| --- | --- |
| Earlier packager refusal after compilation | [Original composition attempt](../testing/evidence/dotnet-memorypack-composition-2026-10-01.json) |
| Offline signed attempt before the entropy adapter, ending in a guest trap | [Original node attempt](../testing/evidence/dotnet-memorypack-offline-node-2026-10-01.json) |
| Exact noncrypto entropy adapter composition | [Component observation](../testing/evidence/dotnet-memorypack-entropy-composition-2026-10-01.json) |
| Fresh normal-node recovery, grant denial and original finite owner/dormant observations | [Recovery receipt](../testing/evidence/dotnet-memorypack-entropy-recovery-2026-10-01.json) and [retained driver](../testing/evidence/dotnet-memorypack-entropy-recovery-2026-10-01-driver.txt) |
| Current resource-index integration, ordinary stream lookup and explicit wall-clock conversion | [.NET resource/clock reconciliation](https://github.com/KirilsTurkins/latent-service-fabric/blob/200c17c26b24d6bf06d8d28102362ea714c1f4eb/docs/development/phase4-handoffs/2026-10-12/pr856-reconciliation.md) |

An enforced restart still obeys the original
[trusted-clock lease](../reference/package-admission.md#clock-leases-retries-and-fresh-admission).
The successful recovery fixture waits through its recorded five-second floor
within the original workflow deadline; an immediate restart refusal is retained
as a separate observation. Application updates cannot reuse that fixture's
approval or infer a durable outcome from a timeout.

Supported reflection/trimming, private-feed authentication and identity
variation, update/remove/watch and broader memory/cancellation/disposal/GC
qualification remain required by #687. Task/ThreadPool and ordinary HttpClient
retain their own runtime tickets. The focused signed resource checks establish
the named standard lookup path, not universal compatibility for NuGet packages.

The captured outside-library gate also checks a resource-backed type initializer, ordinary caught exceptions/finally, UTF-8/binary embedded bytes and zero prior activation state. Requests to that same library exercise an uncaught exception, the original retained-allocation strategy, fuel exhaustion and an observed cancellation. Each known terminal failure requires bounded guest memory, physical idle ownership and a successful fresh signed invocation. Cancellation observes the exact running activation first and issues one mutation; uncertain completion never retries. The existing NativeAOT recipe, runtime profile, entropy declaration, invocation/control bounds and 75-minute job remain unchanged. Terminal interruption does not claim that managed finally clauses run after the Store has stopped. Current-head hosted compiler/node results remain required before this programme is qualified.

The additive delivered-tool watch programme prepares two versions of an outside NuGet library with the shipped pinned compiler, actual managed DLLs and embedded data. Normal add/resolve with explicit native lock update, exact review, recipe trust and signed-fixture preparation run through the maintained frontend. The original source preparation and selected feed are removed before guest compilation. Updating and removing the package must fail before review; changed reviewed recipes require new trust, and old signatures refuse changed builds. Three separately consented signed workspaces must return the initial resource, updated resource and removed result, with unchanged SDK lock and confirmed normal shutdown. The qualifier uses a private unprivileged account, verified delivered compiler expansion and the maintained network-denied compiler namespace. It grants no publisher authentication to a source candidate. Current-head hosted evidence is still required before this watch programme counts as qualified.

That watch fixture copies its explicitly declared random WIT from the verified
vendored SDK, then selects the existing system-random provider through
`prepare-test --consent-test-fixtures --admission signed-fixture --fixtures`.
The selected JSON is
`{"random":{"maximumOperations":16,"maximumOutputBytes":4096}}`: the closed
fixture supports only `bytes`, at most 16 operations, eight input bytes, 4096
output bytes and five seconds. Lower positive operation/output ceilings are
accepted; seeds, output values, alternative operations and extra fields are
rejected. Provider selection grants no authority. The scenario must separately
request the exact random and monotonic-clock capabilities through the normal
policy owner, bound to its service and publication. The ordinary .NET profile
keeps its original monotonic-clock selection; refusing consent leaves providers
and policy state untouched. This source-controlled test selection does not
enable other .NET entropy or runtime APIs.
