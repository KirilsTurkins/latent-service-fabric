# Native-SFI upstream review

Reviewed on 2026-10-15. The revisions below are independently observed source
snapshots, **not a mutually qualified compiler/runtime bundle**. No upstream
tool was built, executed, fuzzed, benchmarked or formally reverified in this
review. Links identify the actual evidence instead of an unbounded `latest`
toolchain download.

## Pinned primary sources

| Source | Reviewed revision and relevant material |
| --- | --- |
| LFI project overview | [`70f7c9e1ea905eb79f3e440506d7a8286ad7ec53`](https://github.com/lfi-project/lfi/blob/70f7c9e1ea905eb79f3e440506d7a8286ad7ec53/README.md): goals, architecture-specific tradeoffs, component repositories and runner defaults. |
| LFI runtime | [`3b78c956368eb78d5d2241cec5d650e13f57f5cb`](https://github.com/lfi-project/lfi-runtime/tree/3b78c956368eb78d5d2241cec5d650e13f57f5cb): [threat model](https://github.com/lfi-project/lfi-runtime/blob/3b78c956368eb78d5d2241cec5d650e13f57f5cb/README.md), core API, Linux layer and runner. |
| LFI verifier | [`b4cf559ab2f66bcbadacef2f138486efb2638970`](https://github.com/lfi-project/lfi-verifier/tree/b4cf559ab2f66bcbadacef2f138486efb2638970): [policy/API](https://github.com/lfi-project/lfi-verifier/blob/b4cf559ab2f66bcbadacef2f138486efb2638970/src/include/lfiv.h), Arm64 and x86-64 verification implementations. |
| Standalone rewriter/post-linker | [`1389430d371cf614e1d3ff8f7487d54d560692d9`](https://github.com/lfi-project/lfi-rewriter/blob/1389430d371cf614e1d3ff8f7487d54d560692d9/README.md): separate assembly rewriting, x86 post-linking and experimental options. |
| Library binding generator | [`dea6d1e34ff2c8762a78f8acb3afa12667aeb95f`](https://github.com/lfi-project/lfi-bind/blob/dea6d1e34ff2c8762a78f8acb3afa12667aeb95f/README.md): static-library packaging, initialization and trampolines. |
| Toolchain builder | [`5236bf1eeb5292238d925ce8e772bfedd45c4260`](https://github.com/lfi-project/lfi-llvm-toolchain/tree/5236bf1eeb5292238d925ce8e772bfedd45c4260): [README](https://github.com/lfi-project/lfi-llvm-toolchain/blob/5236bf1eeb5292238d925ce8e772bfedd45c4260/README.md) and [source downloads](https://github.com/lfi-project/lfi-llvm-toolchain/blob/5236bf1eeb5292238d925ce8e772bfedd45c4260/download.sh). |
| Upstream LLVM LFI documentation | [`9d90850fe6b01d877a7d7559a097fd4e785b4f5a`](https://github.com/llvm/llvm-project/blob/9d90850fe6b01d877a7d7559a097fd4e785b4f5a/llvm/docs/LFI.md): architecture, linking, modes and implemented rewrite categories. This is the reviewed documentation revision, not a selected LSF compiler. |
| LFI specification sources | [`1a44e55c839f79df2e207639a9f0272038302b3f`](https://github.com/lfi-project/lfi-specification/tree/1a44e55c839f79df2e207639a9f0272038302b3f): a separate specification snapshot, not evidence of runtime conformance. |
| Sotoudeh and Yedidia, FMCAD 2025 | [Automated Formal Verification of a Software Fault Isolation System, arXiv v1](https://arxiv.org/pdf/2508.15898v1), sections II-III; archived [artifact DOI](https://doi.org/10.5281/zenodo.16883694) identified by the paper. The artifact/proof was not rerun. |
| Narayan et al., ASPLOS 2025 | [Segue & ColorGuard](https://zyedidia.github.io/papers/seguecg.pdf), [DOI](https://doi.org/10.1145/3669940.3707249): SFI optimization and address-space scaling across Wasm toolchains and an LFI-based x86 implementation. |

The [LSF source review](README.md#repository-evidence-and-review-scope) has its
own revision pins. Updating any of these inputs requires a new compatibility
review; matching repository names or architecture labels is insufficient.

## Findings that change the integration plan

### The runtime's documented threat model is narrower than LSF's question

The runtime README describes current deployment for libraries written by an
honest party, using `SYS_MINIMAL`. It says hardening for arbitrarily malicious
programs and broader syscall usage is ongoing. It also acknowledges that guest
faults can fault or abort the runtime, with graceful signal recovery ongoing.
This is an upstream scope statement, not an LSF exploit reproduction.
[Pinned runtime threat model](https://github.com/lfi-project/lfi-runtime/blob/3b78c956368eb78d5d2241cec5d650e13f57f5cb/README.md).

**LSF implication:** a successful library demo does not establish containment of
hostile capsules or the requirement that one guest trap terminate only its
activation. A supervisor that kills a failed test process protects the research
harness; it does not supply fault recovery inside a production node.

### Upstream LLVM and the standalone LFI tools have different coverage

The reviewed LLVM documentation supports `aarch64_lfi` and `x86_64_lfi`, initially
with static-PIE linking. Its x86-64 section describes 32-byte bundling and
control-flow, syscall and thread-pointer rewrites. **Memory accesses, string
instructions and stack modification remain marked as not implemented.** The
stores-only and jumps-only options relax memory isolation and cannot alone meet
LSF's confidentiality and integrity requirement.
[Pinned LLVM documentation](https://github.com/llvm/llvm-project/blob/9d90850fe6b01d877a7d7559a097fd4e785b4f5a/llvm/docs/LFI.md).

The separate LFI rewriter includes x86-specific post-linking and experimental
metering options. Its README cautions that experimental options may not work
with the default runtime. The toolchain builder README still describes an
earlier partial AArch64 implementation, while `download.sh` clones upstream LLVM
without an exact commit. Those documents cannot establish a complete, coherent
toolchain. [Rewriter](https://github.com/lfi-project/lfi-rewriter/blob/1389430d371cf614e1d3ff8f7487d54d560692d9/README.md),
[builder](https://github.com/lfi-project/lfi-llvm-toolchain/blob/5236bf1eeb5292238d925ce8e772bfedd45c4260/README.md),
[download script](https://github.com/lfi-project/lfi-llvm-toolchain/blob/5236bf1eeb5292238d925ce8e772bfedd45c4260/download.sh).

**LSF implication:** qualify the exact compiler, sysroot, assembler, linker,
post-linker, verifier, loader and policy together. Neither "LLVM supports LFI"
nor an old "unimplemented" label settles the status of the separate toolchain.
Inspect emitted instructions and final executable mappings for the selected
combination. A rewrite-disable directive must never waive final verification.

### Verifier proof and runtime assurance are separate

The FMCAD paper verifies memory-isolation invariants for an ARM64 LFI verifier
under a particular instruction model and memory layout. It assumes a correct
runtime, including guard mappings and controlled runtime transitions. Its
guarantee allows attempted accesses that trap; it is not application memory
safety. It does not prove LSF host callbacks, cleanup, deadlines or x86-64
execution. The paper's register/layout conventions also differ from the later
LLVM documentation, so proof applicability must be established for the selected
binary and policy rather than inferred from the name LFI.
[Paper, sections II-III](https://arxiv.org/pdf/2508.15898v1).

**LSF implication:** retain the proof's exact artifact, assumptions and covered
configuration. Establish correspondence to the selected verifier and loader;
record uncovered instructions, architecture and runtime behavior as gaps.
Fuzzing and adversarial execution complement that work but do not turn a proof
of one verifier into a proof of the whole backend.

### Defaults and host bridges do not provide LSF authority

`lfi-run` starts with verification disabled and, unless restricted, maps the host
root directory into its Linux layer. Its `-v` switch enables verification; its
filesystem restriction and syscall-passthrough switches are distinct controls.
The CLI is a test/benchmark runner, not an LSF execution profile.
[Pinned runner](https://github.com/lfi-project/lfi-runtime/blob/3b78c956368eb78d5d2241cec5d650e13f57f5cb/tools/lfi-run/main.c).

The core library permits a custom runtime API without adopting Linux emulation.
Library trampolines and SBox offer useful calling mechanisms, including
callbacks and shared buffers; they do not supply LSF grants, typed WIT
validation, accounting or lifecycle ownership.
[Core guide](https://github.com/lfi-project/lfi/blob/70f7c9e1ea905eb79f3e440506d7a8286ad7ec53/docs/LIBLFI.md),
[bindings](https://github.com/lfi-project/lfi-bind/blob/dea6d1e34ff2c8762a78f8acb3afa12667aeb95f/README.md),
[SBox](https://github.com/lfi-project/lfi-runtime/blob/3b78c956368eb78d5d2241cec5d650e13f57f5cb/sbox/README.md).

**LSF implication:** investigate the smallest core interface with no ambient OS
access. Host pointers, callbacks and shared buffers need explicit validation and
ownership; a guest must not cause the host to exercise a more privileged grant
on its behalf.

### Callback exit is not general interruption

The core API's `lfi_ctx_abort_cb` exits a callback without returning to the
sandbox. `lfi_ctx_exit` is valid under `lfi_ctx_run`, and its documented use from
`LFI_INVOKE` aborts. Neither API description establishes asynchronous interruption
of a guest loop with no callback. The header also requires appropriate alternate
signal stacks for safe signal handling with sandbox threads.
[Pinned core API](https://github.com/lfi-project/lfi-runtime/blob/3b78c956368eb78d5d2241cec5d650e13f57f5cb/core/include/lfi_core.h).

**LSF implication:** do not equate return-to-host, a metering flag or a watchdog
notification with bounded guest retirement. Signal handlers, thread state and
the node's existing executor need a separately reviewed integration. The first
experiment must contain a pure infinite loop and observe actual termination.

## Relationship to Wasm and performance

Wasm supplies a constrained input format and explicit imports; Wasmtime compiles
and enforces those semantics. Its sandbox still depends on the engine's correct
implementation. [Wasmtime security documentation](https://docs.wasmtime.dev/security.html).
Native-SFI changes the admitted input and validation pipeline; it does not
introduce machine-code execution to an otherwise interpreted LSF.

Segue & ColorGuard investigates SFI optimizations in Wasm runtimes as well as
an LFI-based implementation. Its results depend on particular workloads,
hardware and runtime configurations. This motivates checking the current
Wasmtime baseline and virtual-address-space layout before attributing a benefit
to a new native backend. It is not an LSF speedup or capacity measurement.
[ASPLOS 2025 paper](https://zyedidia.github.io/papers/seguecg.pdf).

The project overview's SPEC figures and sandbox-count claims likewise do not
include LSF's activation creation, capability calls, interruption and physical
cleanup. Virtual address reservation, committed memory, page tables and RSS must
be measured separately. Use the [like-for-like benchmark plan](evaluation-plan.md#benchmark-design)
before making a performance or density claim.
