# TypeScript capsule qualification

This is developer execution evidence for #546, separate from the beginner
[TypeScript authoring guide](../component-development/typescript-authoring.md).
All ten actual SDK cases have passed; signed-node and printed-guide
qualification is still pending.
This report does not authorize a release or replace newcomer review #345.

## Supported experiment

The compiler uses Node 24.19.0, TypeScript 7.0.2, ComponentizeJS 0.22.0,
jco 1.34.0, esbuild 0.28.2 and weval 0.5.0 with the checked-in dependency lock.
Node is a build tool, not an application-owned runtime process. The component
contains SpiderMonkey; each activation owns its heap, module state and pending
microtasks. No timer, worker, process, DOM, ambient clock, entropy, filesystem
or network capability is added. Effects use declared, host-authorized imports.

The project builder captures the editable TypeScript and authoritative WIT,
vendored SDK and compiler recipe; checks generated declarations and projected
type-graph identity; compiles the captured source; and records the actual
component, package and tool inputs. It does not claim authenticated source,
hermeticity, complete transitive dependencies or reproducibility. The reviewed
async adapter changes only the JavaScript implementation calling convention;
the component exposes the authoritative async contract to Wasmtime.

The supported guest ceiling is 128 MiB, one billion fuel and 120 seconds for
cold invocation. The deliberate multi-operation SDK cases use ten billion
fuel. The nested service SDK caller explicitly reserves 240 seconds; its callee
and all other SDK components retain 120 seconds. Production still delegates
only half the parent's remaining wall time and does not extend either deadline.
These are bounded experimental limits, not performance guarantees.
Dormant services must own no process, OS thread, event loop, listener, execution
cell, provider pool or initialized guest heap. Shared compiler/cache ownership
is measured separately from active guest state.

Authoritative contract derivation runs before guest compiler execution and
rejects public RPC resource parameters/results, including nested owned/borrowed
values. The production packaging regressions exercise this rejection; the
TypeScript builder regression requires failure before invoking the JavaScript
compiler. Declared blob and streaming host resource imports remain supported.
A native builder attempt with a nested `list<own<handle>>` public result and
an intentionally absent JavaScript compiler stopped at the real contract tool
with `unsupported-resource-identity`; no component or completion marker was
produced. This is explicit negative authoring evidence, not runtime admission.

## Retained attempts and compiler boundary fixes

[Run 35934224469](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/35934224469)
at `cb3aab64377eea4a5cb26220a6593b5ca2f8351d` passed all ten actual SDK
tests in 680.29 seconds. The real node then admitted all four attempted signed
packages and committed the greeting, HTTP-status and recovery deployments.
The fourth deployment, shipping at control 015, returned `rpc-failed` /
`cancelled`, with `requestDispatched: true` and `outcomeKnown: false`. One
read-only operation lookup and one audit query both returned `resource-exhausted`;
the retained audit is explicitly incomplete. No mutation was retried and no
eventual commit, dormant population, printed-guide or clean-shutdown success
is claimed. Artifact `10782897442` retains this failed attempt.

Shipping publication was recorded at `2026-09-24T00:02:29.024Z`; the failing
apply, both diagnostic reads and cleanup had ended by `00:02:44.937Z`, 15.913
seconds later. The automated operator had still used the common 15-second RPC
profile and 25-second process watchdog, while this TypeScript node already
allowed 120 seconds. This supports a caller-timeout mismatch, but the failed
receipt alone does not prove the server's final outcome. Only the TypeScript
experiment now explicitly selects the printed guide's existing 125-second
operator wait and a 130-second process watchdog. The 900-second overall limit,
120-second node ceiling, production control leases, binding compilation limits
and ordinary-language waits are unchanged. A separate bounded timing record
now accompanies every control attempt, including read-only failure diagnostics;
the closed CLI receipt is not modified. Four regressions cover default waits,
shorter overall deadlines, count/output bounds and one-attempt failures. The
next complete run must validate this evidence-backed inference.

The corresponding source archive `10781944148` contained 4,062 files and
39,728,405 source bytes, all independently matched to that exact Git tree;
its SHA-256 was
`30af4f50d936ec6fc1e2d6b4a66b515ee310258e5226693236c9e35e86212aaf`.
The separate Phase 3 security receipt passed all 27 entries, including the
concurrent local-service acceptance test; artifact `10782532920` retains it.
These checks do not convert the failed full-node qualification into a pass.

[Run 35930223705](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/35930223705)
at `e40fc4bc89aa2bd302489bb3575ee4286d90ee5d` passed all ten actual SDK tests
in 890.74 seconds, including the compiled secret zeroization/copy checks and
opaque resource owners. The nested service succeeded cold in 95.002 seconds
and warm in 7.852 and 6.933 milliseconds. Denied service invocations remained
denied. Both CI memory diagnostics ran three fresh Stores, with 9,502,720 bytes
initial and peak linear memory for each caller and callee. Caller compilation
took 41.189 seconds and callee compilation 41.324 seconds; diagnostic fuel was
5,484,599 and 2,018,628 respectively. Their SHA-256 identities were
`e75e45ed21b7ccea85fad2f92d001d59f7c83c9f65e3fad5de1d4fc0fb3eaf4f` and
`1a1c2605a5dde43598d16b0b1c19a6bdc1f7f5c6cf781cf5fcd868c1bf4fcfed`.

That run subsequently failed the real node's first signed publication at
control 004 with `unavailable`, `outcomeKnown: false` and `audit-unavailable`;
the bounded diagnostic query retained four audit records, including the
expected unsigned denial and the signed verification failure. No mutation was
retried. Artifact `10781926229` retains the failed run, which reached neither
dormant-service measurements nor the printed guide. This is distinct from the
Go demo-proof failure below. Capsule structural inspection held the authority's
currentness fence across component decoding, preventing the sampler from
renewing its unchanged five-second durable lease. Capsule admission and recovery
now follow the existing web path: one bounded verification reservation owns
structural work outside the fence, then current policy/signatures are checked
under the renewed finite control lease before any grant is created. Retained
receipt and epoch association remain fenced; invocation paths never renew.
Five deterministic regression cases cover preparation beyond five seconds,
shared ownership, policy replacement and both role revocations, expiry,
retirement, clock regression, failed durability and invalid-input cleanup.
The registered cases compiled natively and passed in the authoritative Linux
workspace test step of [run 35934224754](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/35934224754)
at `cb3aab64377eea4a5cb26220a6593b5ca2f8351d`. The separate TypeScript
full-node qualifier progressed to the later control failure recorded above.

The next [Go cross-gate run 35934224433](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/35934224433)
passed all ten SDK cases in 82.46 seconds, all 5/9/17 dormant checks, the tutorials
and trap/memory recovery. Its old continuous four-goroutine scheduling fixture
then trapped at 734,111,290 fuel instead of exhausting the one-billion budget;
artifact `10782339103` retains that failed strict classification. The corrected
fixture rendezvouses with four workers and retains their blocked channels while
the main goroutine exhausts fuel, avoiding unrelated unbounded clock-call churn.
It keeps the same fuel/grants, actual blocked-worker cleanup and strict node
classification. The correction requires a new complete cross-language run.
The Go-only qualifier additionally checks the actual compiled recovery component
for fresh state, a genuine `OutOfFuel` trap and another fresh state, with bounded
clock/random import counts. This diagnostic supplements, not replaces, the
strict admitted node cases. The paired probe WIT and host check also retain
signed/unsigned full-width integers, embedded NUL and empty/nonempty bytes.

The shared Go cross-language gate on the TypeScript branch,
[run 35930223804](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/35930223804),
passed all ten SDK tests in 153.94 seconds and progressed past initial deployment
compilation. Its dormant expansion failed at control 034 with
`signature-stale-proof`; artifact `10780923203` retains the known failed outcome
and audit without retry. The isolated demo policy had allowed proofs for only
60 seconds although its signatures and documented experiment last 30 minutes.
Both demo proof ceilings now use the same finite 1,800-second signature window.
Real publisher/builder cryptographic regressions accept 61, 900 and 1,799 seconds,
reject currentness and signature verification at 1,800, and retain independent
role ceilings. Production proof limits, revocation and finite control leases
are unchanged. This correction still requires successful full-node execution.

[Security run 35930223945](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/35930223945)
caught a stale dependency-inventory digest after the obsolete synthetic runtime
export was removed from the SDK manifest. The manifest still declares no
external packages; its reviewed digest now covers only the real capabilities
and text exports. The fail-closed security assertion remains unchanged, and
all 60 security regressions pass locally (one platform-specific test skipped).

[Run 35926422583](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/35926422583)
at `27f0bb21111fbdf778ad9ecb759b213734d95e4f` passed the first cold nested
service invocation in 82.891 seconds, including a successful child in 42.388
seconds. The child's observed peak was 9,502,720 bytes and the caller's aggregate
peak, including the child, was 19,005,440 bytes. The next request correctly
failed admission because the test fixture's one-shot synthetic load sample was
older than the unchanged 60-second admission limit. The fixture now publishes
its synthetic current load at each new request, like its missing node monitor;
it neither retries the failed request nor weakens production freshness checks.
The attempt passed nine of ten SDK tests in 669.71 seconds, but remained failed
before full-node or guide qualification. Artifact `10779964328` retains it.

[Run 35922509041](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/35922509041)
at `cf6767285352ad8b5508f0675fa612cde175aa87` built all fourteen components and
passed nine of ten admitted SDK cases, including opaque blob and streaming
owners. Only the child-service case failed, returning a typed deadline error.
Its actual random and blob diagnostics measured cold compilation at 42.046 and
41.809 seconds. A 120-second caller spending about 42 seconds on compilation
leaves a child share below 39 seconds, insufficient for another cold engine
compile. The explicit service-caller reservation above covers both cold
components without changing the production half-remaining delegation rule.
Caller/child terminal observations and per-invocation elapsed time are retained
in subsequent SDK logs. This failed attempt remains distinct from success.

A Windows diagnostic ran the retained Linux-built caller and callee in three
fresh successful Stores each. Both initialized and peaked at 9,502,720 linear
memory bytes; caller fuel was 13,949,625 and callee fuel was 10,485,358. The
caller component SHA-256 was
`128601601beea2d0dcaa53acba955846953d6a0e0fdda37c161f9e4bb9db4b1b`;
the callee was
`ee99027302b1da43cb01ddff38d064daa1eb0e7d102a6afa12a4fe3724744886`.
With a 128 MiB parent, the unchanged half-remaining memory grant exceeds the
observed child memory, so no TypeScript memory ceiling was raised. The first
caller diagnostic incorrectly registered a synchronous component signature
and failed before instantiation; the corrected diagnostic uses the original
async signature. Its synthetic reply is only for memory measurement, not
admission or authorization proof. CI retains the same two actual-component
memory probes in addition to the production caller/child terminal observations.

The matching [broad CI run](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/35922509604)
also caught an unintended expansion of ordinary buffered-web parser limits when
the larger TypeScript capsule envelope was introduced. Web profile selection
now preserves the original two-million-operator and 65,536-type-node ceilings;
the separately reviewed Angular binary envelope is unchanged. The existing
actual Angular rejection regression remains required, in addition to the new
unit boundary test. No failing assertion was removed or weakened.

[Run 35916800437](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/35916800437)
at `15295c4cd7a1caaca74f904a7cc35b10c77779d4` built all five standalone and
nine SDK components. Seven of ten actual admitted SDK cases passed: signed
admission, blob cancellation, events, buffered HTTP, metrics, random and secrets.
Blob ownership, streaming ownership and child-service invocation still failed;
the run is failed evidence, not a completed guest SDK qualification.

The pinned ComponentizeJS embedding needed signed i64 bit patterns and signed
core i32 representations for WIT unsigned lowering. WIT types and lifting were
not narrowed. The actual random SDK diagnostic checks unsigned maxima and a
declared error crossing the generator's separate JavaScript realm. Error
wrappers recognize only the generated error shape and closed declared payload;
ordinary exceptions still trap.

The obsolete draft synthetic-broker runtime export was removed. Its value and
ownership models remain under `tests/model` solely for supplementary regression
tests; independent projects vendor only the real capability wrappers and text
helpers. The unused ambient-API guard was removed. The checksum-pinned compiler
disables ambient runtime features and rejects surviving WASI imports.

Inspection of actual generated blob glue found references to opaque resource
classes that the generator had not defined. A pinned-shape adapter supplies
only those exact owners and one-shot canonical destructors. It invalidates
before effects, accepts resource representation zero, never retries a throwing
drop and performs no GC-triggered host effect. Unrecognized generator shapes
are rejected. Generated glue is retained for diagnosis. Ten owner/lowering
regressions pass locally, and an actual compiled blob SDK diagnostic returns
the expected values in three fresh Stores with exactly-once drop observed
before Store destruction. This diagnostic is not production admission proof.

The shared child-service fixture now permits only the exact child service
principal for its callee publication where a managed runtime requires clocks.
Production authorization is unchanged. The Go qualification additionally
keeps its explicit runtime entropy budget; TypeScript does not acquire ambient
runtime entropy or clocks through this fixture.

## Required final evidence

The final gate must pass all ten actual provider/ownership cases, covering
buffered/streaming HTTP, blobs, secrets, events, local service invocation,
randomness and metrics. Owners must release normally and on failure, denial,
budget exhaustion and cancellation without retrying uncertain effects.
The actual secret component observes zeroization of its owned bytes, unchanged
application copies, idempotent close and rejection of post-close access; these
checks do not rely only on the supplementary ownership model.

The signed real node must reject unsigned publication, enforce source-bound
builder approval, execute valid/invalid tutorials and allowed/denied HTTP,
and recover with fresh state after deadline/cancellation/disconnect, trap,
fuel and memory exhaustion. Startup, active owners, bounded shared caches and
dormant populations of 5, 9 and 17 must be measured, followed by deletion and
clean shutdown. All six printed Bash guide steps must execute unchanged.

After the guide's pinned prerequisites, reproduce in a fresh output directory:

```sh
python3 tools/qualify_typescript_capsules.py --tools "$LSF_TYPESCRIPT_TOOLS" \
  --output "$(mktemp -d)/typescript-authoring"
```

Only `qualification.json` with `status: passed` after every stage, retained
source-bound receipts and passing exact-head PR CI approve delivery. Failed
attempts remain failed. Final PR and issue evidence must identify the source
and successful run; this document does not qualify release publication,
100k deployment scale, clusters or transactional state. #345 remains separate.
