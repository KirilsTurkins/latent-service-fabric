# Second-pass investigation: ownership composition and parser bounds

This continuation of [#696](https://github.com/KirilsTurkins/latent-service-fabric/issues/696)
keeps [ADR-0059](../../adr/0059-defer-general-outbound-streams.md)'s **defer** decision
but makes two previously descriptive risks executable. It does not promote a raw
stream capability or an SMTP product. Source identities, observed outcomes and
remaining gaps are separate below.

## Finding 1: a gateway has an independent physical owner

A typed gateway reduces the guest authority surface, but adds an external
execution boundary. The following implication is invalid:

```text
LSF HTTP future/session reclaimed => gateway socket/job stopped => peer rolled back
```

The production [broker](../../docs/runtime/capability-broker.md) and
[I/O contract](../../docs/runtime/async-host-io.md) already distinguish cancellation,
retirement and possible external effects. The new
[gateway boundary regression](../../crates/latent-http/src/tests/gateway_boundary.rs)
exercises this distinction with the **actual sealed broker, original activation
ledger, IoRuntime, ProviderPools and HttpProvider**, not a second broker model.

A controlled TCP HTTP peer accepts the first typed POST and records a downstream
effect, then withholds its reply. A channel signals that exact point. Cancelling
the original activation produces `Uncertain`. After completion/session destruction,
the broker observer and host I/O/pool counters are quiescent while the peer's
explicit operation owner remains live. A fresh activation opens an independent
connection and completes a different request. Only an explicit retirement signal
releases the first peer owner; both recorded effects remain. Readiness uses
channels, not elapsed sleeps. A ten-second watchdog bounds the whole scenario;
`JoinSet` owns peer tasks even when assertions fail.

The helper runs inside the existing registered
`tests::http::lost_mutation_reply_is_uncertain_and_never_retried` test. Its original
lost-reply/no-retry checks are preserved. This extends that contract without a new
unregistered test name, duplicate executor or per-ticket CI workflow.

**Evidence boundary:** the peer is a controlled HTTP effect/ownership witness,
not a real SMTP/database service. The fixture constructs real broker authority
around synthetic component metadata; it does not run a Wasmtime Store or guest.
The separate Go SMTP proof does not compose with this Rust regression. Production
DNS/credentials, required durable audit and descendant-call composition are not
newly qualified by it.

The Rust source was first committed as
[`cc97d0a682075b5a99c43534ec95f564fdb425e3`](https://github.com/KirilsTurkins/latent-service-fabric/commit/cc97d0a682075b5a99c43534ec95f564fdb425e3).
Its [CI run](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/36475260722)
is the remote execution record. At the recorded review checkpoint, formatting,
workspace compilation, Clippy, harness build and exact test discovery had passed;
test execution was still in progress. This document does not convert that
checkpoint into a test pass. The native receipt does not include any Rust result.
Use the run's actual conclusion and exact head when assessing completed coverage.

### Consequence for any later gateway approval

LSF accounts its HTTP/provider owners only. An independently operated gateway must
account its own concurrency, queues, socket/kernel/TLS buffers and cleanup; these
cannot be refunded because LSF timed out. A client-supplied timeout only narrows
an authenticated gateway policy and is not inherited authority. Bind tenant,
operation, downstream destination and credential identity on the gateway side;
never trust caller-supplied tenant/destination strings alone.

Closing the client transport may request gateway cancellation but cannot prove
stoppage or rollback. A gateway that retains work after disconnect requires a
finite operational owner and explicit status/reconciliation semantics. It must
not replay uncertain work or treat an idempotency key as universal deduplication.
No durable status store, gateway authentication or delegation format is delivered
by this experiment; these remain separate approval/conformance requirements.

## Finding 2: byte caps are not a protocol parser profile

The inspected [Go 1.23.2 textproto reader](https://github.com/golang/go/blob/go1.23.2/src/net/textproto/reader.go)
uses an unbounded-line mode and allows FTP-style continuation text. Its multiline
reader accumulates reply strings. The [SMTP client](https://github.com/golang/go/blob/go1.23.2/src/net/smtp/smtp.go)
uses that reader. An overall 16 KiB transport cap alone neither enforces SMTP's
512-byte reply line nor bounds each individual multiline reply separately.
[RFC 5321 sections 4.2 and 4.5.3.1.5](https://www.rfc-editor.org/rfc/rfc5321.html)
provide the reply framing and base line-length rules. The experiment negotiates
no extension that increases these bounds. The 16-line/8 KiB total is an explicit
local resource profile, not a claim that every valid SMTP server uses that limit.

The real-library negative test passes a 513-byte greeting to `smtp.NewClient`.
The unguarded library accepts it; the guarded transport rejects it before any
SMTP command. These comparison cases use finite joined `net.Pipe` peers. The
original real TCP/TLS scenarios also run with the guard installed.

The first attempted guard counted bytes but returned the valid-looking partial
prefix with an error. The parser accepted that unterminated prefix as a greeting.
The actual failing command, source hashes and failure text are retained in
[deepening-negative.json](evidence/deepening-negative.json); failed intermediate
sources are identified by digest, not claimed as a checked-in release.

The implemented [reply owner](reply_bounds.go) therefore buffers **one complete
line** before exposing any of it to the parser. It requires CRLF, valid matching
status prefixes for continuations, at most 512 bytes per line and at most 16
lines/8 KiB per reply. Invalid/truncated lines do not escape as success. After a
terminal error, new writes are rejected, including the library's HELO fallback.
The line buffer is fixed and cleared; no asynchronous read-ahead or worker is
introduced. One-byte reads are deliberately conservative and unbenchmarked.

The pre-connect operation reservation increases from 16 to 32 KiB to include the
line owner and a parser/copy allowance. The exact-under-limit test proves this
reservation can deny without connect. This does **not** measure every transient
Go allocation or TLS/certificate buffer. The old allocator/secret-copy concerns
remain production blockers rather than being erased by a new constant.

## Evidence changes and reproduction

[deepening-receipt.json](evidence/deepening-receipt.json) records the actual native
run: **20 top-level Go tests, 63 cases including subtests and six Python evidence
checks**, plus race detection, Go vet and formatting. All sixteen original Go
tests were rerun unchanged. Go 1.23.2, Python 3.13.5 and exact source/library/tool
identities are recorded; a laboratory compiler is not a production recommendation.
The new cancellation barrier retains **131,355 logical bytes** until retirement,
then asserts zero live handles, operations and bytes. No RSS or latency SLO is
inferred from this functional observation.

```sh
python3 research/outbound-streams/run.py --native-only --output target/outbound-streams/native.json
python3 research/outbound-streams/run.py --verify target/outbound-streams/native.json
```

Receipt format 2 recomputes the complete selected source set and all top-level Go
tests from every test file. It requires the six command identities in order,
the exact race-test command and matching observed Python count. Tests reject
omitted/added/modified inputs, missing or duplicated top-level cases, skips,
unknown tests, duplicate JSON keys, traversal and weakened command profiles.
It does not statically enumerate arbitrary dynamic subtests or prove authenticity
of caller-written observations. Hash verification is not an execution signature.

The original [receipt](evidence/receipt.json) stays unchanged. Its version 1
verification belongs to commit `1a91f79f254e3484b514b2b142e7e05d0e240881`, not the
modified current tree. Native-only explicitly excludes the five schema/map tests;
use the default full runner to select all eleven Python tests. Neither profile
parses WIT or executes Rust or guests. The current full profile was not rerun for
the retained native receipt.

## Acceptance delta

| Criterion in #696 | Added artifact or check | Remaining boundary |
| --- | --- | --- |
| 2: compare gateway/provider/stream options | Separate host and gateway ownership analysis | No authenticated production gateway |
| 5: finite resources and cleanup | Fixed reply owner, parser reservation and Rust external-owner barrier | No kernel/allocator/TLS hostile-peer memory qualification |
| 6: mutation uncertainty | Cancellation after effect, no implicit retry, successful fresh activation while external work remains live | No rollback or remote transaction guarantee |
| 8: bounded prototype and source evidence | Real SMTP negative/control tests, all original network cases rerun; real-broker regression source and CI identity | No combined guest-to-HTTP-to-SMTP run; no local Rust execution |
| 9: decision and evidence integrity | Versioned complete-input verifier, immutable prior evidence, this decision addendum | Architectural approval and production promotion remain separate |

The six-language compatibility investigation and uninstalled WIT/schema proposal
are unchanged; their unexecuted compiler and WIT-conformance qualifications are
not newly claimed. These findings strengthen the **defer** decision: typed
boundaries are useful, but neither a gateway nor a library transport callback
eliminates parser, authority, external ownership or recovery obligations. Ordinary
library ingestion and HTTP adapters must not wait for raw sockets or this future
production qualification.
