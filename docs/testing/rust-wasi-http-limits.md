# Rust ordinary HTTP individual limits

The selected explicit-async WASI HTTP0.2.12 profile has a signed nine-attempt
limits programme. [Run 39682987900](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/39682987900/job/119509893888)
passed at source `7003c123007c4e87e13296ee48d4472ab743f394` using the unchanged
88b ordinary-client component, 526 backend and c713 native products. No guest,
adapter or native compilation occurred. The [source-bound observation](evidence/rust-wasi-http-limits-2026-10-22.json)
retains all earlier failed limits runs.

| Selection | Actual result | Matched fresh call |
| --- | --- | --- |
| Original Task8/Timer8/16MiB | Parsed Waki and Golem JSON; a real transitive Golem Timer Pending followed by controlled response release | Baseline successful calls |
| Task1 only | First held response entered with five live physical owners and accepted provider work. Waki retained one response, then returned the exact typed `InternalError(Some("latent-runtime-resource-exhausted"))` | Parsed ordinary Golem JSON in the same cell |
| Timer1 only | First held response had an actual Timer Pending1 witness. After release, the second charged outbound start ended in the exact unreachable guest trap | Parsed ordinary Waki JSON in the same cell |
| Requested memory3MiB only | Exact resource-exhausted terminal, no provider/peer contact, unexhausted fuel and all physical owners retired | Original16MiB parsed ordinary Golem JSON in the same cell, with identical operator limits |

The Timer result identifies a single-ceiling differential. It does not identify
the trapping instruction. The Task result combines actual admission/retention
with the selected `Exchange::admit` Task source path; an arbitrary resource error
alone would not identify that owner.

The memory result also depends on source and the exact whole component digest.
Its runtime, application and forwarding-root main cores are all instantiated,
with independent memories of 17, 19 and 17 pages. Their minimum aggregate linear
memory is 3,473,408 bytes, exceeding the 3,145,728-byte request by 327,680 bytes
before other allocations. This is not measured RSS. The original c713 producer
can attach a private `activation.memory-exhausted` detail, but both original
public projections omit that kind. Actual public `details` was `[]`; the exact
private allocation site and instruction remain unknown. Only the fixed-component,
single-memory-request differential plus actual upper-budget fresh success proves
this limit. The old typed-detail-only reader still refuses that public row.

All nine attempts preserve the other original invocation budgets and grants.
Across four separately configured nodes there are 17 complete retirement
observations: all five physical execution owners and all 18 available active
provider counters are zero. All peers closed and all four nodes shut down cleanly
and were reaped. The original 64-attempt programme and six-attempt installed
programme retain their separate observations; neither is repeated here.

## Literal #689 evidence mapping

This mapping concerns the maintained selected profile. It does not require
completion of every feature in #736/#743 and does not advertise general std
threads, Tokio, Rayon, raw sockets or arbitrary runtime implementations.

| Criterion | Evidence for the selected contract |
| --- | --- |
| 1: useful ordinary/default profile below captured crates | Maintained whole WASI0.2.12 backend, normal independent Waki/Golem constructors and compiler-owned root; signed64 plus installed6 |
| 2: original public HTTP/body/error/pending semantics | Signed64 parsed domains/statuses, streamed bodies, pending completion and explicit supported/Unsupported semantics; sync-looking Rust bodies retain the explicitly declared async component effect |
| 3: budgets and selected runtime lifecycle/queues/drop/panic | Signed64 entered pending I/O, cancellation, trap and accepted-work root drain; new Task1/Timer1/memory differential9 under original owner limits, with positive entry and fresh gates. Independent guest executor queues and eligible guest-sibling progress have no signed witness; pre-entry activation-queue cancellation does not prove those clauses |
| 4: bounded bodies/backpressure/Drop/close/drain | Signed64 partial body, early Drop, root Drop/trap, cancellation/deadline and drain; physical/provider retirement, not Drop alone, is the completion proof |
| 5: typed grants and currentness | Signed64 missing provider/grant, denied target zero contact, reserved credentials/framing, redirects, malformed/oversized data, timeout/abort and distinct tenant/publication currentness |
| 6: explicit retry/auth/redirect/pool/options differences | Signed64 controlled mutation peer proves no uncertain-POST replay; exact published library error distinctions, stopped redirects, credential isolation and explicit timeout-option Unsupported |
| 7: activation ownership, late fences and fresh cell reuse | Signed64 cancel/trap/root close with five physical owners retained through teardown, 65 retirement observations and opposite tenant/client fresh calls; new nine attempts add 17 retirements and matched fresh after each isolated ceiling. No guest pool/session survives retirement; no arbitrary quarantined guest execution is claimed |
| 8: optional unprivileged extensions kept separate | Captured ordinary and varied developer-owned crates use the same backend without library registration; optional transport examples remain separately labelled and supply no ordinary-client qualification |
| 9: exact captured inputs and existing installed tooling | Installed6 authenticates the ordinary isolated recipe/inventory, explicit selected world and normal dependency approvals; original backend/tool/compiler/WIT identities and developer-coordinate variation are preserved |

The HTTP, ownership and individual-limit matrix is the union of the [signed64](evidence/rust-wasi-http-signed-2026-10-21.json),
[installed6](evidence/rust-wasi-http-installed-2026-10-21.json) and individual-limit9
observations. The selected profile exposes no guest executor/thread API. Its
Pump polls every retained readiness owner before blocking, but source alone is
not a signed sibling-progress witness. The literal independent-queue/fairness
clause of AC3 is therefore still unproven; this limits slice does not close the
whole ticket or make a blanket ecosystem/native ABI promise.

## Historical and composed source

The actual archive has 427 SHA/CRC-checked members, 197 executed Git inputs,
116 historical recipe rows, and the original 3,325 native plus 134 auxiliary
identities. The qualified source snapshot remains immutable.

Composition onto development `4e973393...` preserves 192 of those 197 input
files. Three later #1318 producer/wire/CLI diagnostic files expose a closed public
memory/fuel dimension only in future products; the c713 observed empty details
are not rewritten. The other two deltas are #1317 display-only compatibility
rendering and a Go-only v6 profile spelling. Exact before/after identities and
meanings are listed in the observation. This composition is not another native
build or a repeat qualification of the current tree. The original owning branch
and verifier retain the actual 7003 source for reproduction.
