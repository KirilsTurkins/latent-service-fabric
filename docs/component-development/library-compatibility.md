# Dependency compatibility reports

The maintained Rust, C, TypeScript, Go, Java and .NET authoring recipes inspect
the final component's imports and exports before packaging. A changed declared
surface or an import outside the recognized host ABI stops packaging. The
retained `compatibility-inspection.json` identifies the component and ABI inputs.
The existing package validator additionally checks the complete WIT types.

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

Add `--json` to validate and emit the same machine report. This command only
reads the explicit report; it does not execute library code or grant authority.
