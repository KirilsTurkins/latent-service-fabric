# PR #800 external transaction clients

## Issue and scope

PR #800 implements the additive external transaction client slice of
[#401](https://github.com/KirilsTurkins/latent-service-fabric/issues/401).
Rust, C, TypeScript Node, Go, Java and C#/.NET expose the sixteen maintained
StateService, TransactionService and DispatcherService operations through their
existing transports. Current stateless operations remain supported. No issue
is automatically closed.

The original source head is `5d41e9b481e78818db4ac2a8ff30095301e61f94`.
Normal integration of development `01a0192678d9a068b6cdcfda3727740e93cfc29f`
preserves current runtime ownership, retention, authenticated recovery, security
diagnostics, Go 1.27.2 and the reviewed Java 25 toolchain. The new generation
checks extend the SDK CI job without removing required commands or guards.
All nine Go protobuf inputs and all sixteen .NET generated sources remain
registered. The reviewed .NET transport and Java Gradle build fingerprints
follow their additive transaction protobuf inputs and executable transport
suites. Their original feature fingerprints match the retained source; package
versions and the current development security inventory remain intact.

The shared models preserve original command/attempt/operation identities,
publication, fingerprint, unsigned counters, nullable presence, opaque tokens,
bounded pages and independent audit/provider facts. Cancellation and lost
responses retain recovery data; the clients do not automatically resubmit
mutations or refresh expected versions. TypeScript management transport stays
in the Node export. The optional staging witness remains descriptive; this node
adapter reports absence when its observer is not installed.

## Snapshot decisions

Central preservation #850 and portable handoff #978 retain the exact original
head and its earlier source, native and SDK results. Those results remain
attributed to their recorded source revisions.

.NET malformed-peer snapshot #930 contains the finite request-body drain before
a deliberately malformed HTTP/2 reply. That fix is already present in the
original client branch and is preserved: an unread Kestrel request must not turn
the intended protocol refusal into a transport reset.

SDK fixture checkpoint #882 concerns mocked guest compiler imports and entropy
qualification under #677. It supplies context for those fixtures and introduces
no additional external-client transport implementation. The integration handoff
#959 concerns #823/#828 and the separate signed query/recovery collector #879.
Those guest and installed-runtime campaigns are not merged into this client PR.

## Validation boundaries

The maintained transport peers exercise actual sockets and protobuf codecs;
their controlled outcomes test client ownership and protocol handling. They do
not qualify the production node's durable business behavior. Historical receipts
and their explicit qualification flags remain unchanged.

Issue #401 still requires the reviewed separate-node pairing for every client:
state change with a pending effect, durable business rejection without writes,
authorization refusal and revocation, conflict, cancellation before/after commit,
lost committed/rejected responses, restart, result expiry, bounded query/history
and in-flight shutdown. Installed preparation/profile selection and the complete
management profile also remain required. Guest execution belongs separately to
#389/#718; the browser boundary belongs to #409. No 36-way matrix is claimed.

Compiled discovery adds the nine Rust client schedules and one neutral process
compatibility case while preserving all existing test names and ignores.
Fresh validation is recorded after reconciliation; hosted CI is not awaited
after push.

## Current local validation

Pinned Rust 1.97.1 runs all 348 cases across the selected RPC, SDK, testkit and
wire library/integration targets. The 23 original wire ignores remain unchanged.
The Rust SDK executes all sixteen cases, including its nine new transaction
schedules. Workspace formatting passes. Ordinary SDK/wire Clippy and the
required strict latent, latentd, latent-testkit and latent-admission checks pass.

All six clients receive fresh Linux transport validation:

| Client | Pinned tools | Result |
| --- | --- | --- |
| Rust | Rust 1.97.1 | Sixteen library cases and existing integration targets pass |
| C | Existing locked native dependencies | Normal and sanitizer builds pass; all sixteen transaction methods and 62 shared protobuf vectors execute |
| TypeScript Node | Node 24.19.0, TypeScript 7.0.2 | Semantic checks and all 38 transport tests pass without skips |
| Go | Go 1.27.2, Buf 1.72.0 | Two generation checks, all packages and complete transport race checks pass |
| Java | Temurin 25.0.4.1+1 | 1,271 non-preview Java 25 classes; semantic fixtures, twelve original transport suites and six transaction suites with 120 checks pass |
| C#/.NET | SDK 8.0.425, runtime 8.0.31 | Two clean generations, exact locked graphs and signatures pass; 656 transport checks, 62 protobuf cases and 78 semantic records execute |

The three transaction model/conversion/Rust-shape regeneration checks pass.
All ten Go generation-controller tests and four .NET generation-controller tests
pass. The initial Java attempt correctly refused the older installed Windows
JDK; current Linux qualification uses the exact reviewed JDK, verified against
its official release archive digest. The Go helper retains real Git provenance
through the original repository object mount.

The actual Gradle 9.1.0 `clean check` entry point passes on the pinned Linux JDK,
including all three executable suites. Bytecode verification checks 2,517 entries
across class directories and the JAR, all targeting non-preview Java 25.

All 3,676 maintained Python cases run on pinned Python 3.13.5 Linux: 3,658 pass
and the 18 existing host/tool guards skip. The security regressions pass with
both reviewed SDK build fingerprints reconciled. CI coverage preserves 88
baseline and 275 current required run blocks with 148 delegated owners.
Foundation, documentation and source-contract checks pass.
