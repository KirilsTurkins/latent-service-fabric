# Dependency compatibility reports

The maintained Rust, C, TypeScript, Go, Java and .NET authoring recipes inspect
the final component's imports and exports before packaging. A changed declared
surface or an import outside the recognized host ABI stops packaging. The
retained `compatibility-inspection.json` identifies the component and ABI inputs.
The existing package validator additionally checks the complete WIT types.

Recipes select the frozen V5 manifest only when the authoritative declared WIT
surface explicitly imports `latent:runtime/activation@0.1.0` or
`latent:network/streams@0.1.0`; other surfaces keep the frozen V4 manifest.
The profile selector accepts only those two manifest identities. It neither
falls back after a missing manifest nor derives authority from emitted imports.
V5 inspections record the selected profile and its exact manifest digest;
packaging and failure reporting recheck that digest. Existing V4 inspection
records retain their original shape. Provider installation, exact grants,
runtime support and normal node admission still require their own evidence.

V4 recipes require only their existing V4 manifest. A declared V5 surface adds
the exact V5 manifest to the retained recipe inventory before its first use;
the final recipe recheck includes that input. .NET and TypeScript derive the
surface before compilation. Adapters that derive staged WIT afterward capture
the additional observation input before inspecting and packaging the result.
Adding that input cannot hide a changed original recipe. A missing or changed
V5 manifest fails the build. A compiler bundle retains the manifest for its
explicitly advertised ABI profile, while V4 bundles need no V5 material.

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

`blocked` means a retained observation identifies a concrete blocker.
`incomplete` means observations leave unresolved behavior, lifecycle or optional
extension use. `observed` describes only the retained observations; it is not a
certificate of general library compatibility. Compiler elimination requires a
source identity and compiler evidence. A scan for an API name cannot prove
reachability or elimination.

`unsupported-reached` requires an initialization, invocation or retirement
observation labelled `actual-component` or `native-reference`. Compile/link,
static, model and unevaluated evidence cannot claim that execution reached the
operation. A native reference retains its distinct label and does not qualify
an emitted component. Every `actual-component` finding requires a component
digest, including findings that would otherwise be omitted by the retention
limit; readers and text presentation also reject unbound claims. These checks
validate the report's evidence labels and identity, not the truth of an execution
receipt or the all-language compatibility matrix.

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
