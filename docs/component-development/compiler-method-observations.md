# Java and .NET compiler method observations

The maintained Java and .NET builders accept an explicit `build --compiler-methods`
option. It is off by default. Select it when building an application for which
compiler dependency observations are useful; collecting diagnostics alone does
not require executing an application or its initializers on the compiler host.

The selected build writes `compatibility-compiler-methods.json`, or a closed
`compatibility-compiler-methods-unavailable.json` when collection is missing,
incomplete, stale or outside its bounds. The original compatibility report and
normal compiler failure remain authoritative. This observation supplies no
provider installation, grant, execution permission or successful build override.
The selected/unavailable disposition is bound by the canonical
`compiler-method-observation-selection` build material; the native signer's
closed Java/.NET recipe parameters remain unchanged.

Java passively reads the actual javac output and captured transitive JARs, then
queries TeaVM 0.15.0's completed dependency analysis. The SDK listener does not
link methods, change instructions or load application classes on the host.
`linked` means dependency-linked or potentially retained; it does not prove
final code generation or execution. `not-retained` concerns only the exact
queried method in that completed dependency analysis.

.NET requests the pinned NativeAOT scanner graph during the selected normal
build. The actual ILC response file identifies the input assembly, captured
application references and private scanner graph. A passive metadata reader
maps a finite nongeneric ECMA method subset using the pinned compiler's naming
and metadata iteration rules. Unsupported spellings and generic instantiations
remain unmapped; compiler-synthetic methods without ECMA definitions are outside
the query set. Every declaration still participates in collision
ordering. At least one exact positively retained unmanaged-export anchor from
the actual root assembly must match before absence of any mapped query is
reported. An unexpected namespace or writer shape makes the observation
unavailable. Scanner retention is separate from final code generation.

The public sidecar contains at most 64 methods and 64 KiB, exact omission counts
and safe bounded symbols or opaque identifiers. Source, component, compiler,
recipe and captured dependency graph identities bind the result. Raw JVM
descriptors, ILC response arguments, paths and DGML labels are not published;
the private graph stays in the normal temporary build directory.

All method API classifications remain `unknown`. A native declaration alone
does not establish an unsupported API. Compiler absence does not prove that
reflection, generated code or another configuration cannot reach an operation.
Runtime execution and worker drain require their own source-bound actual
observations. These collectors have focused metadata and parser controls;
their new application-level compiler and signed runtime matrix remains pending.

The dedicated compiler-compatibility programme captures two ordinary transitive
libraries per language through normal review and offline authoring. It compiles
one substantive signable component per language with the option selected. Java's
normal compiler-cache acquisition may additionally build its existing unsigned
control; that control supplies no initializer or callback qualification.

The fixture performs six real calls: caught filesystem refusal during static
initialization and construction, caught refusal in an ordinary Timer or Task
callback, an uncaught initializer branch, a fresh call, an uncaught callback
branch, and another fresh call. Each completed activation must release the cell,
all physical activation owners and all 18 provider counters. One missing-runtime
grant call must be rejected before guest entry. The original fuel, memory,
120-second invocation and activation-owner limits remain fixed. No filesystem,
logging or network authority is added. The managed fixture explicitly selects
the maintained Task profile with monotonic clock, wall clock, random and
activation declarations; Java uses the maintained fiber-I/O profile.

Java then changes exactly one root call while keeping both reviewed JARs
byte-identical. Its expected compiler failure must identify that precise original
native declaration. Only the combination of completed positive queries, actual
positive compilation and that concrete refusal supports the finite eliminated
operation. A missing .NET wrapper stays an unknown API result.

`compatibility-outcomes.json` uses the existing redacted actual-outcome reader.
A separate `compatibility-execution-report.json` records only the exact fixture's
validated caught fallback and counterfactual observations. The packaged report
is unchanged. Generic uncaught traps keep unknown causes, and arbitrary worker
drain remains unproven. The owning artifact retains bounded public results and
the signable component/package for causal replay; it excludes private DGML,
response files, query labels, signing keys and application temporary directories.
These are source-reviewed programme obligations; signed results remain pending.
