# Native software fault isolation

Native software fault isolation (native-SFI) constrains native machine code so
that it can execute as an untrusted guest within a host process. A compiler or
rewriter produces a restricted instruction stream; a verifier checks the final
code before a loader permits execution. Restricting memory accesses alone is
insufficient: control transfers, runtime entrypoints and privileged operations
must preserve the sandbox boundary. An application can still corrupt its own
data inside that boundary.

**Status: exploratory, with no LSF native-SFI backend, prototype, execution
receipt or benchmark.** This review proposes obligations and experiments; it
does not demonstrate containment. Research must not become a required production
dependency. No candidate native-SFI artifact may execute in the node's main
runtime address space until memory, control-flow, syscall, timeout, capability
and activation-lifecycle containment have been demonstrated against adversarial
tests and approved through a promotion ADR.

Start with the [upstream review](upstream-review.md) for pinned primary sources
and their limits, then the [evaluation plan](evaluation-plan.md) for the artifact
contract, negative cases, measurements and decision gates. The website's
[native execution guide](../../docs/runtime/native-sfi-research.md) explains
which execution paths are currently available.

## Repository evidence and review scope

Reviewed on 2026-10-15 against documentation-stack parent
[`c5763c49bc010d3f4c34a5bba7c37390d7593339`](https://github.com/KirilsTurkins/latent-service-fabric/tree/c5763c49bc010d3f4c34a5bba7c37390d7593339).
The supplied development snapshot
[`90cf1f4c87ca24e9a64b077dc2eb501dcef22441`](https://github.com/KirilsTurkins/latent-service-fabric/tree/90cf1f4c87ca24e9a64b077dc2eb501dcef22441)
was retrieved and compared without changing this PR's parent. Neither source
contains an implemented native-SFI track. The two revisions are not
interchangeable qualification identities.

| Finding at the reviewed stack parent | Source and implication |
| --- | --- |
| Wasmtime 48.0.6 is selected in both the workspace and runtime constant; the supplied development snapshot selects 48.0.5. | [Cargo.toml](../../Cargo.toml), [runtime configuration](../../crates/latent-wasmtime/src/config.rs), [security upgrade record](../../docs/development/wasmtime-security-update.md). Versioned or historical evidence does not qualify the other engine. |
| The research track had only its short charter. | [Original track at the reviewed parent](https://github.com/KirilsTurkins/latent-service-fabric/blob/c5763c49bc010d3f4c34a5bba7c37390d7593339/research/native-sfi/README.md). This update adds analysis, not an implementation. |
| No `native-sfi` backend selector exists; standalone manifest validation rejects non-Wasm execution. | [Backend enum](../../crates/latent-manifest/src/lib.rs), [manifest validation](../../crates/latent-manifest/src/validation.rs). Adding an executor trait implementation would not enable native packages. |
| Preparation, currentness, typed transaction input, cancellation and cleanup have explicit owners. | [ExecutionBackend](../../crates/latent-executor/src/lib.rs). Its default report path quarantines a backend that supplies no cleanup proof. Its artifact/preparation contracts are not a generic native ABI. |
| Each invocation creates a new Wasmtime store with resource and interruption controls. | [Invocation setup](../../crates/latent-wasmtime/src/backend.rs), [engine policy](../../crates/latent-wasmtime/src/config/engine.rs), [containment](../../crates/latent-wasmtime/src/containment.rs). A native backend would need equivalent lifecycle evidence. |

These are source observations, not fresh runtime qualification. Existing
[validation boundaries](../../VALIDATION.md) still apply.

## Native-SFI and existing AOT answer different questions

LSF already executes native instructions produced from WebAssembly components.
Its [trusted-local AOT path](../../docs/runtime/trusted-aot.md) compiles with
Wasmtime, authenticates the output under a protected local authority and loads
it through Wasmtime. The configured compiler, loader, engine, host bindings and
OS remain trusted. A signature proves an association with bytes and policy; it
does not make arbitrary native code safe.

```text
Implemented: application -> Wasm component -> Wasmtime compilation
                        -> authenticated/local native output -> fresh Store

Research:   application -> restricted native compilation/rewriting
                        -> final-code verification -> proposed SFI activation
```

The proposed path needs its own artifact format, verifier policy, loader and
host ABI. Existing native-cache receipts cannot be relabeled as native-SFI
admission. Similarly, Wasmtime's use of SFI techniques does not mean LSF already
supports independently supplied native executables. See the
[upstream comparison](upstream-review.md#relationship-to-wasm-and-performance).

## Obligations inherited from LSF

These requirements derive from the current runtime and architecture. They are
not guarantees supplied by an upstream compiler.

| Boundary | Obligation for a candidate backend |
| --- | --- |
| Fresh activation | Immutable prepared code may be retained. Mutable globals, heap, stack, TLS, libc state, callbacks and handles belong to one activation; no prior activation's data or authority may survive reuse. Constructors, traps and destructors are part of this lifecycle. |
| Dormant deployment | Retain code and bounded metadata, not a native application, guest thread, heap, socket or pool per deployment. Fixed execution capacity must remain independent of service count. |
| Host authority | Recognition of an ABI, provider installation and an activation's grant remain separate. Native callbacks must retain the original identity, deadline, accounting owner and current policy. No ambient filesystem, network, environment or syscall authority. |
| Bounded execution | A loop with no host calls must be interruptible within a declared bound. Client timeout, cancellation delivery or an unpolled future does not prove execution stopped. |
| Cleanup and reuse | Return reusable capacity only after guest execution, callbacks, provider work and descendants have retired or transferred to an explicitly bounded owner. Quarantine is not a refund or evidence of termination. |
| Typed calls and transactions | Define argument/result ownership, errors, async completion and resource handles. Preserve validated transaction parameter identity, exact host/budget association and start-fence currentness, or reject that profile explicitly. A symbol named `invoke` supplies none of this. |
| Preparation and admission | Bind immutable code validity separately from current publication authority. Revoked, retired or differently scoped content must not gain execution through held readiness or cache objects. |

The detailed owners are described in [execution cells](../../docs/architecture/execution-cells.md),
[activation containment](../../docs/development/activation-containment.md),
[capability brokerage](../../docs/runtime/capability-broker.md),
[host ABI profiles](../../docs/runtime/host-abi-profile.md),
[publication runtime](../../docs/reference/publication-runtime.md) and
[installed transactions](../../docs/development/installed-transaction-rpc.md).
The [evaluation matrix](evaluation-plan.md#adversarial-cases-and-required-observations)
turns these obligations into falsifiable tests.

## Compatibility and security limits

The initial research target is Linux x86_64 and one bounded C computation, not
six language runtimes. Arm64 results, Windows execution and experimental RISC-V
support require separate treatment; an ARM64 verifier proof cannot qualify an
x86-64 deployment.

Native-SFI does not implement Java/Node.js/.NET APIs, terminate library-created
work, or translate a listener into an LSF endpoint. The
[dependency compatibility contract](../../docs/component-development/library-compatibility.md)
and [finite server declaration model](../../docs/component-development/server-source.md)
still need language-specific execution and ingress evidence. In particular, a
network grant for an HTTP method/path does not authorize an opaque socket API.

Current [security profiles](../../docs/runtime/execution-security-profiles.md)
continue to describe the delivered Wasmtime boundary. There is no native-SFI
profile, stronger process-compromise guarantee, kernel boundary or strong
side-channel claim. A different verifier/runtime adds a different trusted
computing base; its effect must be reviewed rather than inferred from the word
"native."

## Research disposition

LFI is a concrete candidate for an isolated feasibility study, not a selected
LSF dependency. Its runtime's documented honest-library threat model, incomplete
upstream compiler coverage, and unqualified interruption/fault recovery are
material promotion gaps. See the pinned findings in the
[upstream review](upstream-review.md#findings-that-change-the-integration-plan).

Proceed only with a bounded harness and the [decision gates](evaluation-plan.md#promotion-decision).
If containment or physical retirement cannot be established, retain the negative
result and defer the in-process backend. Performance or successful compilation
cannot waive those requirements.
