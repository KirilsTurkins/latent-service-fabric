# Call-graph fusion: literature and component composition

Reviewed on 2026-10-15. This is primary-source analysis; no paper artifact, WAC
build, fused application or performance experiment was run. Published results
belong to the authors' platforms, workloads and isolation assumptions.

## Research evidence and transfer limits

| Primary source | Contribution and implication for LSF |
| --- | --- |
| [Baldini et al., The serverless trilemma, Onward! 2017](https://research.ibm.com/publications/the-serverless-trilemma-function-composition-for-serverless-computing) | Identifies tension between black-box functions, synchronous substitution and avoiding double billing in a reactive runtime. For LSF, service-call equivalence and resource accounting must be defined before changing execution boundaries; cloud billing is not the same as LSF's conserved descendant ledger. |
| [Faastlane, USENIX ATC 2021](https://www.usenix.org/conference/atc21/presentation/kotni), [paper](https://www.usenix.org/system/files/atc21-kotni.pdf) | Co-locates workflow functions as threads, uses MPK isolation and processes/containers where parallelism needs them. It separates fast data exchange from the isolation mechanism. Its thread/process model and OpenWhisk baseline do not establish fresh LSF Store, capability or cleanup semantics. |
| [WiseFuse, SIGMETRICS 2022 extended abstract](https://schaterji.io/papers/WiseFuse_SIGMETRICS_22__Extended_Abstract.pdf) | Studies DAG transformation and resource allocation, including fusion of serial work and bundling of parallel work. Group selection must account for resource demands and contention. The reviewed source is an extended abstract, not an LSF implementation or a full reproducibility packet. |
| [Fusionize++, arXiv 2311.04875v2, 2024](https://arxiv.org/html/2311.04875v2), [publication DOI](https://doi.org/10.1109/TCC.2024.3451108) | Uses monitored task dependencies, a fusion handler and resource sizing. Its Node.js/AWS Lambda prototype routes same-group tasks locally and other tasks over HTTPS. Developers follow its programming model. This supports feedback-driven candidate selection, not transparent composition of arbitrary preexisting LSF components. |
| [Konflux, arXiv 2601.11156v1, January 2026](https://arxiv.org/html/2601.11156v1) | Explores fusion configurations using local FaaS emulation and varying resource/pricing assumptions. Useful for candidate-search methodology; an emulator's best configuration is not an LSF production optimum or proof under mixed load. Treat this version as a preprint. |
| [Provuse, arXiv 2603.06170v2, March 2026](https://arxiv.org/html/2603.06170v2) | Platform-side fusion of independently deployed functions is close to LSF's authoring goal. The Python prototype targets tinyFaaS and Kubernetes and assumes one trust domain because fusion reduces isolation. LSF cannot infer equivalent authority or failure containment from co-location. |
| [Faasm, USENIX ATC 2020](https://www.usenix.org/conference/atc20/presentation/shillaker) | A closer Wasm-based comparison: SFI-isolated functions, selectively shared memory and initialized snapshots reduce data movement/startup costs. Its sharing, POSIX and snapshot model differs from LSF's capabilities and fresh activation ownership; those choices require qualification rather than wholesale adoption. |

Provuse's evaluation uses two applications across two platforms, with 10,000
requests per experiment at 5 requests/second. It reports average reductions of
about 26.3% in median latency and 53.6% in RAM. Those are limited workload/platform
observations, not an LSF target or high-load guarantee.
[Evaluation and discussion](https://arxiv.org/html/2603.06170v2).

LSF local calls already avoid remote transport and per-service containers. Its
baseline includes compiled bindings, prepared code and fresh in-process child
activations. The transferable questions are which boundary costs remain,
whether grouping changes isolation or resource policy, and how quickly build
costs are amortized before releases or policies invalidate the candidate.

"Synchronous" in these papers often means the caller depends on a callee's
answer. LSF's `async` WIT function kind describes an execution interface; it does
not by itself prove a dependency is independent, parallel or safe to fuse.

## Pinned composition sources

| Source snapshot | Reviewed material and limit |
| --- | --- |
| [WAC `5a7480c69ae7a4dc9eb161f485cbcb8c95e372c9`](https://github.com/bytecodealliance/wac/tree/5a7480c69ae7a4dc9eb161f485cbcb8c95e372c9) | [README](https://github.com/bytecodealliance/wac/blob/5a7480c69ae7a4dc9eb161f485cbcb8c95e372c9/README.md), [workspace](https://github.com/bytecodealliance/wac/blob/5a7480c69ae7a4dc9eb161f485cbcb8c95e372c9/Cargo.toml), [graph encoding](https://github.com/bytecodealliance/wac/blob/5a7480c69ae7a4dc9eb161f485cbcb8c95e372c9/crates/wac-graph/src/encoding.rs) and [component types](https://github.com/bytecodealliance/wac/blob/5a7480c69ae7a4dc9eb161f485cbcb8c95e372c9/crates/wac-types/src/component.rs). The workspace identifies 0.12.0 and declares wasmparser/wasm-encoder 0.258.0. This is not a selected LSF dependency. |
| [Component Model `2e7895c76905cd3fb7e6be4ac632258972b1f688`](https://github.com/WebAssembly/component-model/tree/2e7895c76905cd3fb7e6be4ac632258972b1f688) | [Explainer](https://github.com/WebAssembly/component-model/blob/2e7895c76905cd3fb7e6be4ac632258972b1f688/design/mvp/Explainer.md), [Canonical ABI](https://github.com/WebAssembly/component-model/blob/2e7895c76905cd3fb7e6be4ac632258972b1f688/design/mvp/CanonicalABI.md) and [concurrency design](https://github.com/WebAssembly/component-model/blob/2e7895c76905cd3fb7e6be4ac632258972b1f688/design/mvp/Concurrency.md). These describe component/instance, value, resource and async semantics, not LSF admission or an adopted fusion design. |
| Component Model book | [Composition](https://component-model.bytecodealliance.org/composing-and-distributing/composing.html) and [component design](https://component-model.bytecodealliance.org/design/components.html) explain type-directed linking and memory separation. Consult the pinned design sources when assessing exact behavior. |

WAC's function-type representation includes `is_async`, and its encoder emits
that property. It is therefore inaccurate to assume composition tooling is
categorically synchronous-only. Conversely, source support for an async type
does not qualify the complete LSF canonical service import, target export,
adapter and Wasmtime combination. The [reviewed LSF source](README.md#reviewed-source)
uses a different wasmparser baseline; demonstrate compatibility with exact
artifacts instead of inferring either compatibility or incompatibility from
version numbers alone.

## What composition does and does not remove

### Type composition is not service dispatch

WAC connects compatible component imports and exports. LSF's canonical
[`service.call`](../../wit/platform/invocation/package.wit) takes a target,
payload bytes, media type and options, then returns success, declared error or
platform failure with bounded values. An application's `tax.calculate` export
has its own business signature. Wiring those together needs an adapter that
preserves target checks, payload validation, limits and outcome conversion.

The [codec](../../docs/protocol/wit-values.md) defines positional arrays,
normalization, nested values and sole top-level declared errors. A caller may
observe the byte sequence. An optimizer needs evidence that an avoided
conversion/copy is unobservable; type compatibility alone cannot erase the byte
protocol, its audit digest or its error behavior.

### Component memory separation is not fresh logical invocation

The Component Model separates immutable component definitions from mutable
instances. A composed graph normally instantiates its members and connects
their calls; it does not promise to recreate a callee for every business call.
Separate memories therefore do not settle the repeated-callee counterexample
in the [semantic contract](README.md#meaning-of-a-preserved-service-call).
[Pinned explainer](https://github.com/WebAssembly/component-model/blob/2e7895c76905cd3fb7e6be4ac632258972b1f688/design/mvp/Explainer.md).

LSF's existing Store also owns its host state and execution controls. A shared
Store would need member-aware host dispatch, fuel/deadline handling, result
ownership and failure conversion. WAC supplies none of those LSF owners. Guest
constructors must not run speculatively before a logical child's audit,
authorization and admission boundary merely because its code was prefetched.

### Typed resources and async edges need lifecycle evidence

Canonical lifting/lowering, resource identity, borrowing, reentrancy and async
completion remain part of a composed execution's semantics. They are not a
license to retain guest buffers or reuse handles across logical activations.
[Canonical ABI](https://github.com/WebAssembly/component-model/blob/2e7895c76905cd3fb7e6be4ac632258972b1f688/design/mvp/CanonicalABI.md),
[concurrency design](https://github.com/WebAssembly/component-model/blob/2e7895c76905cd3fb7e6be4ac632258972b1f688/design/mvp/Concurrency.md).

The first LSF experiment should keep the currently admitted value surface and
ordinary child lifecycle. Future, stream or resource support in a composition
tool cannot expand an LSF profile by implication. Cross-language type linking
also does not remove each guest runtime's initialization or heap.

## Research recommendation

Use joint preparation as the first measurable candidate, then a small composed
artifact as a separate mechanism experiment. Report exactly which boundaries
are preserved, emulated or changed. Treat Store/cell merging, shared mutable
state, speculative execution and permission union as semantic design choices
requiring decisions and evidence. The [evaluation plan](evaluation-plan.md) and
[benchmark protocol](../../benchmarks/fusion/README.md) define the next work;
the literature does not establish an LSF speedup.
