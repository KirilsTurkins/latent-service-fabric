# Dependency compatibility reports

The maintained Rust, C, TypeScript, Go, Java and .NET authoring recipes inspect
the final component's imports and exports before packaging. A changed declared
surface or an import outside the recognized host ABI stops packaging. The
retained `compatibility-inspection.json` identifies the component and ABI inputs.
The existing package validator additionally checks the complete WIT types.

Recipes select from four frozen manifest identities using the authoritative
declared WIT surface. `latent:http/phase-timing@0.4.0` selects V7.
`latent:state/key-value@0.2.0` or `latent:intents/staging@0.1.0` selects Phase 4;
combining either transaction interface with phase-timing is refused. Otherwise,
`latent:runtime/activation@0.1.0` or `latent:network/streams@0.1.0` selects V5,
and other surfaces keep V4. The selector accepts only these known manifests;
it neither falls back after a missing manifest nor derives authority from
emitted imports, provider installation or grants. Non-default inspections record
the selected profile and its exact manifest digest; packaging and failure
reporting recheck that digest. Existing V4 inspection records retain their
original shape. Runtime support and normal node admission still require their
own evidence.

Recipes retain the exact selected manifest before its first use, and the final
recipe recheck includes that input. .NET and TypeScript derive the surface before
compilation. Adapters that derive staged WIT afterward capture the additional
observation input before inspecting and packaging the result. Adding that input
cannot hide a changed original recipe. A missing or changed selected manifest
fails the build. A compiler bundle retains the manifest for its explicitly
advertised ABI profile; V4 bundles need no unselected profile materials.

Each package contains `compatibility-report.json`, a source-bound observation
using `lsf.guest.compatibility.v1`. Its identity binds the source inventory,
component, selected host ABI and SDK lock. The report does not install providers,
grant capabilities, approve a package or authorize a retry. Package signing and
admission remain separate steps in the [guest workflow](guest-sdk.md).

If a later build step fails, the packaged report remains byte-identical.
Additional observations use `compatibility-failure-report.json`; raw compiler
components use `compatibility-raw-report.json` when a shared report already
exists. Each diagnostic keeps its own component identity. An unavailable or
stale diagnostic input still produces `compatibility-report-failed.json` and
preserves the original build failure.

After the recipes recheck immutable inputs, `compatibility-context.json` binds
the existing report, source and component to selected compiler materials,
owner-emitted standard-runtime receipts and automatic patch identities. Patch
records distinguish original bytes, transformed bytes and the recipe plus
configuration identity. Runtime selection remains unqualified; absent runtime
observations, unknown reachability and initialization, and unproven worker drain
remain visible. This separate sidecar does not replace the packaged v1 report.

Java activation builds also display the selected TeaVM compiler JAR and its
coroutine, array-root and monitor source corrections, with separate original
and transformed digests. These come from the bound generated-bindings receipt
and must match its loaded JAR and replacement classes. Invocation diagnostics
recheck that receipt and the recipe before using the projection. These identities
describe the compiler selection; API compatibility remains unknown.

Selected TypeScript `buffer`/`node:buffer` builds also present the finite
`lsf-node-buffer-v1` module profile as **SELECTED**, with qualification unknown
and authority none. Its complete receipt/backend/declaration subgroup binds the
selected sidecar to the recorded authoring recipe and captured SDK declaration.
Invocation readers recheck those same identities against the original owner's
`toolAndCompilerInputs` receipt and recipe entries before applying the context.
This records module selection independently of package identity; it neither
certifies an unchanged npm dependency nor installs a grant or global Buffer.
Unselected captures retain the ordinary generic presentation.

The context also retains dependency identities from the exact captured source
inventory. It displays each retained dependency's original archive and selected
tree digests, and its captured version when the resolver recorded a bounded
version label. An absent or unsafe version stays `not-observed`; it is never
guessed from the package name. Registry configuration and arbitrary package
metadata are excluded. Go replacements use their effective source version; a
local replacement never borrows the superseded module's version. Runtime and
patch entries precede dependency attribution
within the existing 64-material, 64-KiB bounds; omitted materials are counted.
Linked libraries share capsule authority. An attributed package is not a
separate security principal, and this metadata supplies no execution evidence.

The normal node test workflow writes `compatibility-outcomes.json` from each
original invocation result. It retains the frontend source separately from the
compatibility source inventory, redacts payloads/messages, and validates the
closed node diagnostic vocabulary and unsigned counters. It issues no extra
invocation, status request, retry or grant. Queue pressure and generic resource
errors do not identify a task, timer or stack limit. A client process being
reaped does not establish a library worker's physical retirement. These sidecars
describe observed selections and outcomes, with unknown API compatibility.

Rust, Go, C and TypeScript builds also record the maintained owner's automatic
selection in `standard-runtime-selection.json`. It binds the captured runtime
sources, selected dependency graph, compiler/recipe materials, WIT input
inventory, generated binding result and build configuration. No application
runtime patch is required. The receipt identifies the runtime implementation
and qualification owner; it does not certify arbitrary APIs, transitive
callbacks or lifecycle quiescence. Renaming a package changes its captured
graph identity without changing API eligibility. These receipts remain beside
the build and preserve the packaged compatibility report and asset identity.

`compatibility-reachability.json` additionally inspects bounded compiler-emitted
core code. It follows direct calls from all core exports, start functions and
observed addressable callbacks, using a conservative superset of the component's
selected exports. A closed core graph can identify a function without an emitted
root path. That observation does not prove API elimination, actual execution,
transitive library reachability or successful initialization. Indirect dispatch,
tables, opaque instruction encodings and analysis limits remain unknown. The
sidecar binds source, component, runtime/host profiles, selected graph and recipe;
it never runs initializers. At most 64 findings and 64 KiB are retained, with
explicit omission and symbol redaction counts. Source locations remain explicitly
unobserved when the emitted code supplies no authenticated mapping.

```sh
python -m tools.guest_emitted_code output/compatibility-reachability.json --context output/compatibility-context.json
```

Reports distinguish dependency resolution, target/ABI problems, unsupported
operations, missing runtime implementations, unqualified profiles, unknown
behavior, optional application extensions, provider installation, grants,
resource limits, deadlines, cancellation, physical cleanup and uncertain effects.
Task, thread, frame, queue, timer, guest-memory and native-memory failures can
retain their particular resource. A cancellation acknowledgement does not prove
physical retirement. An uncertain external operation does not become retryable.

Typed engine memory and fuel interruptions retain their public
`activation.memory-exhausted` or `activation.fuel-exhausted` detail with the
matching `memory-bytes` or `cpu-fuel` dimension. Wire and CLI readers omit the
private cell identity and backend reason, and reject mismatched dimensions.
This identifies the producer's resource class; it does not identify an allocation
site, prove physical retirement, or classify a generic resource-exhausted error.
Older hosts can omit this detail, which remains unknown to public readers.

`blocked` means a retained observation identifies a concrete blocker.
`incomplete` means observations leave unresolved behavior, lifecycle or optional
extension use. `observed` describes only the retained observations; it is not a
certificate of general library compatibility. Compiler elimination requires a
source identity and compiler evidence. A scan for an API name cannot prove
reachability or elimination.

Java and .NET offer explicit, default-off
[compiler method observations](compiler-method-observations.md). Dependency or
scanner retention stays separate from API support and actual execution; missing
or incomplete observations remain unknown.

The additive Rust diagnostics programme uses an outside captured crate and its
transitive callback crate through the ordinary Cargo authoring and lock-review
workflow. It removes the original sources before the network-disabled build,
then signs the component with the same run's existing native products. Native
reference processes exercise ordinary thread creation; the selected closed Wasm
profile must return the catchable `Builder::spawn` unsupported error, retain an
explicit application fallback, expose an uncaught `thread::spawn` as a terminal
failure, and pass a separate fresh invocation with reset library state. Each call
is reaped and followed by actual node/provider idle observations.

Only an exact successful decoded fallback can create the source-bound
`unsupported-reached` observation. A generic terminal trap remains unresolved;
the report does not infer its cause, retry safety or general worker quiescence.
The fixture's target-selected branch checks are not promoted to arbitrary API
elimination. The [retained signed Rust result](../testing/evidence/rust-compatibility-signed-2026-10-21.json)
passed all four cases on development source `7f169e7d2279f71bc10adaaac58625ae914fe8ed`:
catchable denial with explicit fallback, the target-selected branch, an uncaught
terminal trap, and a fresh successful fallback invocation after the trap. Each
case has an idle physical node observation; the node shut down cleanly and was
reaped. Its original machine report remains `blocked`, because the selected
closed profile does not implement thread creation. The native references remain
separate. Initialization failure, arbitrary API elimination, arbitrary worker
quiescence and the six-language diagnostics matrix remain unqualified.

`unsupported-reached` requires an initialization, invocation or retirement
observation labelled `actual-component` or `native-reference`. Compile/link,
static, model and unevaluated evidence cannot claim that execution reached the
operation. A native reference retains its distinct label and does not qualify
an emitted component. Every `actual-component` finding requires a component
digest, including findings that would otherwise be omitted by the retention
limit; readers and text presentation also reject unbound claims. These checks
validate the report's evidence labels and identity, not the truth of an execution
receipt or the all-language compatibility matrix.

Observed grant denial, resource exhaustion, deadline, cancellation and uncertain
external completion also require initialization, invocation or retirement evidence
labelled `actual-component` or `native-reference`. Compiler, final-import, model
and unevaluated observations cannot assert those runtime outcomes. A native
reference remains a reference, not proof that the emitted component behaved the
same way. Missing grants, unqualified profiles and unproven lifecycle remain
separate conservative findings when execution evidence is unavailable.

The current package report inspects the final interface names. It conservatively
leaves runtime initialization, transitive callbacks, actual provider/grant
configuration and retirement unproven. Successful compilation does not qualify
default library constructors or concurrent runtime behavior. Those require
actual-component evidence from the selected runtime and library workflow.

Ordinary packages have no catalogue eligibility check. Compatibility depends on
the selected target, actual API implementation, limits and explicit authority.
HTTP method/path authority cannot authorize an opaque socket import. A proposed
runtime port remains an implementation gap until its emitted components pass
the relevant qualification.

Findings carry finite classifications and optional source/package digests,
relative locations and emitted symbols. Raw exception text, source contents,
credentials, absolute paths and unbounded backtraces are excluded. At most 64
findings are retained, with an explicit omission count. Truncation remains
incomplete. To read the report as concise developer text, run from the SDK
checkout:

```sh
python -m tools.guest_compatibility output/compatibility-report.json
```

Add `--context output/compatibility-context.json` to present the separately bound
standard-runtime and patch context. It must match the report's source/component
identity. `--json` continues to emit the original v1 report on its own.

The text includes retained package/source digests, relative locations and safe
emitted symbols, followed by the context's selected/original runtime and patch
identities. Symbols containing host paths or credential-like text are redacted.
Displaying these observations does not alter their machine report or infer a
cause, API elimination, qualified runtime or permission from a dependency name.

Generated transformations with both recorded original and transformation digests
are also displayed, including maintained SDK binding generation. Their selected,
original and transformation identities stay separate. A generated tool input
without those records is not presented as a transformation. The
[six retained context observations](../testing/evidence/compatibility-generated-transform-display-2026-10-21.json)
show the four previously hidden binding transformations; Java and .NET output
stays identical. These are reader observations of original compiler contexts,
with no additional build or execution qualification.

Add `--outcomes output/compatibility-outcomes.json` to include the original
invocation observations. The reader checks the closed diagnostic fields, numeric
bounds, report/component identity and, when supplied, the matching context before
printing any report. The frontend source identity stays separate from the
compiler inventory. A node-reported resource exhaustion can retain an unknown
resource dimension; queue pressure and coarse error codes do not identify a
library failure. Missing or invalid context and omitted observations remain
visible. Client reaping does not prove physical retirement, and no outcome grants
a retry right. These presentation options read existing files and issue no calls.

An observed `activation.guest-trap` detail with the closed
`runtime-lifecycle-unproven` code is retained in `guestTrapCode` and displayed as
a runtime disposition. It records the node's lifecycle refusal without
identifying the outstanding owner, resource dimension or library operation.
Cause remains unknown without the existing numeric diagnostic evidence;
physical retirement and worker drain remain unproven even when the invocation
client was reaped. Unknown, conflicting or oversized trap details do not supply
a runtime disposition. Messages, cell identifiers and private detail fields are
excluded from the observation.

The separate node-owned `activation.guest-trap-kind` detail now retains its
closed engine classification in `guestTrapKind`, such as `stack-overflow` or
`unreachable-code`. A `runtime-error` may also retain the fixed
`guestRuntimePhase` label. These fields require a matching original trap code;
unknown, duplicate, contradictory or private-bearing details produce only
`trapKindUnavailable`. This distinguishes an observed engine failure without
identifying an unsupported API, a particular quota, library reachability or
physical retirement. [Two retained actual results](../testing/evidence/compatibility-trap-kind-reader-2026-10-20.json)
exercise the new reader; this is no additional guest execution or six-language
runtime qualification claim.

The text reader also names the existing node-owned numeric diagnostic stage,
reason and optional profile. For example, stage `3` and reason `4` are displayed
as `preparation (3)` and `unsupported-engine-profile (4)`. These labels describe
the producer's observation; they do not identify a reached library operation,
prove a missing API implementation, or certify a package. In particular,
`queue-pressure` does not identify a task, thread or timer limit. The existing
cause and resource-dimension fields keep their separate evidence rules.

When supplied by the node, `configured_bound`, `calculated_requirement`,
`fixed_bytes`, `lifting_fuel` and `lift_multiplier` are displayed as their exact
unsigned measurements. Zero stays zero; absent measurements and profiles are
not invented. Missing and invalid-present diagnostics are labelled separately.
Unknown enum values, duplicate observations, oversized numbers and private or
unrecognized diagnostic fields supply no display labels or measurements. The
reader makes no additional call, changes no invocation result, and retains the
same source bindings, redaction, retirement and retry limitations.

Add `--json` to validate and emit the same machine report. This command only
reads the explicit report; it does not execute library code or grant authority.

The optional [versioned compatibility catalogue](../compatibility-catalogue/README.md)
indexes retained package observations separately from these API diagnostics. Its
content keys bind exact package graphs, configurations, compiler/runtime/backend
inputs and original evidence. Catalogue membership grants no authority and is not
a dependency resolution, build or admission input.

The separate [six-language API/runtime matrix](runtime-capabilities.md) identifies
finite implemented and qualified surfaces, explicit profile limits and proposed
ports without using sample package names as API eligibility. Its versioned data
binds source files and original evidence; it installs no runtime or authority.

The [six-language final-import control](../testing/evidence/six-language-final-import-controls-2026-10-21.json)
checks actual retained C, Rust, Go, TypeScript, Java and .NET components with
`wasm-tools 1.254.0` and the normal final-component inspector. Each original
passes. A declaration-only suffix adds the callable
`diagnostic:unknown/final-import@0.1.0` interface while preserving every original
byte, core module, initializer and existing import. Both binaries validate; the
inspector then rejects the added interface as `unknown-import` at link time.
No guest is compiled, signed or executed by this check. Runtime compatibility,
permission, fallback and physical retirement still require their own evidence.

To reproduce, restore `component.wasm` and `capsule.json` for each language into
`INPUTS/LANGUAGE/`, matching the exact file and origin identities in
`tools/tests/fixtures/final-import-components.json`, then run:

```sh
python -B tools/qualify_guest_final_imports.py --inputs INPUTS --output NEW_OUTPUT --wasm-tools PATH_TO_WASM_TOOLS
```

The fresh output contains the original and changed components, actual WIT,
refusal reports and bounded command diagnostics. The index-space decoder refuses
unsupported forms or bounds; it never treats its own decoding as Wasm validation.
The published record includes all 32 successful tool calls, source and original
input hashes, and the two earlier control failures and their precise corrections.
