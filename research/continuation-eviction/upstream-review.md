# Continuation eviction: compiler and durability evidence

Reviewed on 2026-10-15. This is source/literature analysis, not a qualified
compiler/engine bundle, deployed workflow system or performance result for LSF.
The source snapshots below were inspected, not built or executed.

## Compiler capture and live control transfer

| Primary source | Contribution and scope |
| --- | --- |
| [Kappa, SoCC 2020](https://vivi.sh/assets/papers/kappa.pdf) | Generates continuation functions at transitive pause points and serializes live state. Waiting tasks can terminate their invocation and resume later. Its Python prototype excludes constructs including `try/except`, `yield`, `async/await`, nested definitions and globals. External calls run through coordinator tasks; the paper's nonduplication statement assumes no coordinator failure. This is not universal language persistence or exactly-once arbitrary I/O. |
| [Stopify, PLDI 2018](https://people.csail.mit.edu/rachit/files/pubs/stopify-pldi18.pdf) | Source transformation provides JavaScript execution control using reified continuation frames. Section 3.1.1 treats restoration through exception handlers/finalizers explicitly, and constructors need special handling. Frames include function references and live values; execution control alone is not a portable durable encoding or workflow protocol. |
| [Emscripten Asyncify documentation](https://emscripten.org/docs/porting/asyncify.html) | Compiled-Wasm unwind/rewind transformation, with instrumentation overhead and difficult indirect-call analysis. Manual exclusions can break execution; reentrancy and rewinding with compiled code already on the stack have constraints. Documentation examples do not qualify LSF's Component Model, host owners or six language heaps. |
| [Binaryen Asyncify source `74ff1eb9cc8393f16854014667e540a3ba883b97`](https://github.com/WebAssembly/binaryen/blob/74ff1eb9cc8393f16854014667e540a3ba883b97/src/passes/Asyncify.cpp) | Inspected pass implementation, last changed 2026-07-21. It saves call positions/locals in a selected linear memory using module globals. Its comments explicitly exclude unwinding within Wasm-exception `catch` blocks; the ignore-unwind-from-catch option is documented unsafe in general. Pinning this file does not qualify an Emscripten/Binaryen distribution. |
| [WasmFX: Continuing WebAssembly with Effect Handlers](https://arxiv.org/abs/2308.08347) | Typed continuations support composable control flow and lightweight concurrency. This is not a persistent-checkpoint or external-resource reconstruction protocol. |
| [Stack-switching explainer `154ac34a38b38a840c99dc8cd795a3d06aff5e65`](https://github.com/WebAssembly/stack-switching/blob/154ac34a38b38a840c99dc8cd795a3d06aff5e65/proposals/stack-switching/Explainer.md) | Inspected text, last changed 2026-04-07. Its one-shot operations invalidate a consumed live continuation. That rule does not arbitrate two durable checkpoint copies or fence a stale process after recovery. |

**LSF implications:** instrumentation coverage must include transitive callers,
indirect calls and supported runtime/library paths. An unsupported path needs
an explicit diagnostic before durable work is accepted, rather than silently
ignoring a suspension. Test captured exception values, pending returns and
constructor identity, as well as ordinary successful locals.

Unwinding for capture must not run application cleanup as if the operation had
finished. Conversely, terminal cancellation/error must retain the selected
language's cleanup semantics. Distinguish compiler control transfer, guest
finalization and physical Store retirement. These are proposed LSF qualification
obligations, not claims that the sources implement them for LSF.

## The selected Wasmtime baseline

This stack pins Wasmtime 48.0.6 at
[`72bc45bd197c46718df0c02b8d4cbc1cb610ab2d`](https://github.com/bytecodealliance/wasmtime/tree/72bc45bd197c46718df0c02b8d4cbc1cb610ab2d).
Its [embedding documentation in source](https://github.com/bytecodealliance/wasmtime/blob/72bc45bd197c46718df0c02b8d4cbc1cb610ab2d/crates/wasmtime/src/lib.rs)
describes async execution on a separately allocated native stack and switching
back when host work is pending. That is efficient scheduling, not a serialized
execution state. The
[`Component::serialize` implementation](https://github.com/bytecodealliance/wasmtime/blob/72bc45bd197c46718df0c02b8d4cbc1cb610ab2d/crates/wasmtime/src/runtime/component/component.rs)
copies the compiled engine image; it does not capture an instance or pending calls.

The [February 2025 Wasmtime discussion of suspended-fiber serialization](https://bytecodealliance.github.io/zulip-archive/stream/217126-wasmtime/topic/Serialize.20suspended.20fiber.html)
explains stack/register relocation across process address spaces. Treat this as
dated engineering context, not a supported snapshot API or implementation-cost
estimate. The charter excludes arbitrary native-stack capture in any case.

LSF's [prepared-code/AOT path](../../docs/runtime/trusted-aot.md) can reduce code
preparation on restore. It cannot replace continuation payloads, fresh host owners,
resume fences or a durable wait registry. Upstream development documentation may
describe a different engine than LSF's selected version; the pinned source is the
baseline for this review.

## Durable execution without language-state serialization

| Primary system documentation | Mechanism and relevance |
| --- | --- |
| [Azure Durable Task orchestrations](https://learn.microsoft.com/en-us/azure/durable-task/common/durable-task-orchestrations) | Commits history and scheduled actions, unloads an orchestrator and re-executes code using recorded results to reconstruct state. This releases execution memory without storing an arbitrary live language stack. |
| [Azure orchestrator constraints](https://learn.microsoft.com/en-us/azure/durable-task/common/durable-task-code-constraints) | Direct time/randomness, external I/O and unmanaged async work conflict with replay. Durable APIs and separately managed activities provide the supported boundary. Replay would introduce a programming contract, not transparently qualify existing capsules. |
| [Temporal workflow definitions](https://docs.temporal.io/workflow-definition) and [event history](https://docs.temporal.io/encyclopedia/event-history) | Replay compares generated commands with durable history. Code changes and intrinsic nondeterminism need compatibility controls; activity work is separate. Long-lived work needs deliberate version handling even without a compiler-generated state layout. |
| [AWS Lambda durable execution SDK](https://docs.aws.amazon.com/lambda/latest/dg/durable-execution-sdk.html) | Checkpoints operation data/results and replays code from the beginning while using completed-operation records. Its use of checkpoint terminology does not imply native-stack or whole-heap capture. |

Three mechanisms must therefore remain distinct: an explicit durable state
machine, deterministic history replay, and compiler-generated continuation
serialization. Compare their costs and supported semantics rather than treating
them as different names for the same feature.

**LSF design inference:** establish a durable transition substrate independently
of the frontend. A captured-continuation frontend may avoid replaying the entire
workflow prefix, but a crash can still require re-executing an uncommitted
segment. Effects therefore need durable identities and uncertainty handling with
either frontend. No source above proves exactly-once guest instructions or
unrestricted external effects for LSF.

## Portability and evidence limits

None of these results qualifies all six LSF compiler/runtime profiles. A core-Wasm
transform does not automatically serialize component resources, references held
outside linear memory, runtime globals, tables, GC objects or host callbacks.
Saving linear memory alone cannot be assumed to cover all of them either.

Record exact compiler, pass options, generated component, continuation schema,
language runtime, host ABI and engine configuration for any experiment. Preserve
the untransformed reference and no-suspension cases. No upstream speedup or
instrumentation percentage is an LSF estimate; measure equivalent contracts,
including normal execution, checkpoint peaks and full restoration/cleanup.
