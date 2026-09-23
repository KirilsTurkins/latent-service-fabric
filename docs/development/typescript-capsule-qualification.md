# TypeScript capsule qualification

This is developer execution evidence for #546, separate from the beginner
[TypeScript authoring guide](../component-development/typescript-authoring.md).
Complete SDK, signed-node and printed-guide qualification is still pending.
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
fuel. These are bounded experimental limits, not performance guarantees.
Dormant services must own no process, OS thread, event loop, listener, execution
cell, provider pool or initialized guest heap. Shared compiler/cache ownership
is measured separately from active guest state.

## Retained attempts and compiler boundary fixes

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
