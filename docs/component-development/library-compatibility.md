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

Add `--json` to validate and emit the same machine report. This command only
reads the explicit report; it does not execute library code or grant authority.
