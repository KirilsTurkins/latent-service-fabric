# Native-SFI evaluation and promotion gates

This is a proposed experiment, not an implemented harness or an instruction to
run unqualified code in LSF. The [upstream review](upstream-review.md) records
known gaps; [LSF's obligations](README.md#obligations-inherited-from-lsf) define
the integration contract. No stage below is complete merely because its design
is written down.

## Proposed semantic and threat model

Assume an adversary controls candidate native bytes, metadata, guest inputs and
all mutable guest state. It may forge host-call arguments, violate an ABI,
attempt forbidden instructions, trap or run forever. Protect the host and other
activations' memory, credentials, policy, handles and finite execution capacity.
This does not establish application correctness, resistance to a compromised OS
or strong side-channel isolation.

The verifier and its decoder, loader and memory protections, runtime entry/exit
stubs, host bindings, node and OS are security-critical. A complete independent
verifier could remove compiler correctness from the instruction-containment
argument, but that must be demonstrated for all executable bytes and transforms.
It does not remove supply-chain policy or trust in runtime support code that is
executed outside the verified guest boundary.

Keep four distinct predicates: final bytes satisfy a particular verifier/layout
policy; prepared code is compatible with its runtime; the publication is
currently authorized to start; and an activation has actually retired. A cached
verified image satisfies neither current authority nor retirement. The proposed
lifecycle is admission and immutable preparation, followed by currentness at the
start fence, fresh mutable activation state, and then either stopped execution
with complete cleanup or quarantine with outstanding ownership retained.
Client completion is an observation, not an additional retirement transition.

## Initial scope and containment

Use Linux x86_64, one pinned C compiler profile and a deterministic bounded
computation with a small typed input/output. Start with no guest threads,
dynamic linking, JIT, guest-supplied native callbacks or ambient OS access.
Exercise one explicitly mediated host-call stub only after basic isolation
works. Language-runtime ports, transaction support and listener lowering are
separate follow-ups, not implied compatibility.

The harness must be a separate supervised process, with a disposable unprivileged
environment, no credentials or network, an explicit syscall/filesystem policy,
finite CPU/memory/output/process limits and an outer deadline with actual
kill/reap ownership. Bound compilation and malformed-input verification too.
Keep candidate executable mappings out of the LSF node. A container without a
reviewed policy does not itself establish those controls.

The supervisor is an experimental safety boundary and failure oracle. Killing
its child proves that child was retired, not that an in-process SFI activation
can be safely interrupted. A failure must remain visible even if the supervisor
successfully cleans up. Do not invoke the permissive default `lfi-run` command as
an adversarial acceptance test.

Before execution, declare finite limits for verification time, executable/data
bytes, committed memory, stack, output, host calls, outstanding buffers and
retirement time. Record the CPU, kernel, page size, address-space layout,
instruction features, toolchain configuration and exact input digests. Start
with one execution slot; scaling and soak campaigns require separate scope.

## Native artifact and host interface contract

Design this contract before a candidate can be admitted. These are proposed
fields and rules, not a new accepted manifest or runtime selector.

| Contract area | Required binding or validation |
| --- | --- |
| Immutable image | Exact final artifact bytes, all executable segments, target ISA/ABI, endianness, CPU features, segment bounds/alignment and finite sizes. Reject malformed/overlapping mappings, unsupported relocations, loader extensions and unexpected dependencies. |
| Production inputs | Compiler, sysroot, rewriter, assembler, linker and post-linker identities and configuration, including runtime libraries and handwritten assembly. Every executable dependency needs the same discipline. |
| Safety policy | Verifier executable/library and decoder identities, specification/proof scope, full read/write/control-flow mode, permitted instructions and runtime-call ABI. A signature or successful compiler exit cannot bypass verification. |
| Loading | Verify the actual executable bytes and relevant addresses after transformations/relocation, or prove the transformation preserves verification. Keep verified bytes immutable; prohibit writable executable aliases and later replacement. Loader-owned generated stubs need their own justification. |
| Publication | Artifact association with exact release/publication, prepared-code identity and host/security policy. Current tenant authority, revocations and lifecycle eligibility remain checked separately at use and the final start fence. A warm cache cannot retain permission. |
| Values and handles | Typed arguments/results, bounds/overflow checks, owned buffers, error/trap forms, async completion, cancellation and handle lifetimes. WIT may describe the contract, but a validated native representation and codec still need design. Never treat a native symbol name as a checked export. |
| Resource ownership | Activation identity, original accounting/budget owner, deadlines, bounded queues and memory/image permits. Shared code and host cleanup must have explicit owners that outlive every borrower. |

Prefer a minimal custom host API over Linux emulation for this first study.
Every host operation must check the activation's exact installed provider and
grant. Copy or otherwise stabilize guest-controlled descriptors before an async
wait; validate nested pointers and lengths, resource kinds and activation
generations. Do not retain raw guest pointers or capability sessions across
activations. Reentry must preserve the original owner; an authenticated native
image cannot confer storage, network, secret or transaction authority.

Reject guest native threads, direct syscalls, arbitrary `dlopen`, executable
memory creation and unreviewed exception/unwind paths in the initial profile.
Constructors, libc initialization, allocation failure, `longjmp`, callbacks and
destructors must not escape the guarded entry/exit path. Preserve host TLS,
signal configuration, reserved registers and floating-point state when returning
to a shared worker.

If transactions are later enabled, the backend must support the existing typed
parameter/currentness and transaction host/budget contracts. Generic JSON
canonicalization or a new callback identity cannot substitute for them. Until
then, fail unsupported transaction preparation explicitly, without a fallback
to an unqualified native path.

## Adversarial cases and required observations

Every row needs positive controls and deliberate violating inputs. Bind the
result to final bytes, policy, runtime and host; record the actual rejection,
trap, termination and retained ownership. A verifier pass alone does not execute
a runtime test. An outer harness timeout is a failed inner retirement bound.

| Case | Required observation before claiming the boundary |
| --- | --- |
| Out-of-region reads/writes | Attempts into host and neighboring sandbox canaries, including wraparound and cross-page/vector accesses, cannot disclose or modify their bytes. Distinguish safe remapping from a trap; do not require application correctness inside its own sandbox. |
| Control-flow escape | Reject or contain branches into the middle of guarded sequences, misaligned/bundle-interior targets, arbitrary host addresses, reserved-register changes and forbidden instructions. Test handwritten assembly and post-link mutations. |
| Executable-byte substitution | Verification cannot be reused for changed file bytes, relocations, alternate mappings, writable aliases or unverified generated stubs. Failed verification never reaches guest execution. |
| Privileged operation | Direct syscalls, namespace/thread creation, executable mappings and ambient filesystem/network attempts are denied. Host-call forgery, wrong provider/grant and cross-tenant arguments cannot turn the host into a privileged deputy. |
| Runaway execution | A no-host-call loop, recursion and metering-bypass variants stop within the declared inner bound. Observe retirement independently of the client response; a surviving guest keeps its reservation and makes reuse fail. |
| Fault and unwinding | Illegal instructions, stack overflow, memory faults, abort/exit paths and FFI exceptions cannot crash or corrupt the containing runtime if activation-only containment is claimed. Supervisor recovery must not be reported as this property. |
| Memory/resource exhaustion | Heap, stack, mapped bytes, output, callbacks and host buffers stop at finite charged ceilings. Include allocator failure and partial initialization; host-side allocations cannot escape guest accounting. |
| Stale handles and state | After A completes, traps or is cancelled, B cannot observe A's globals, heap, stack, TLS, secrets, callbacks, descriptors or handles. Wrong-generation handles fail even when indexes or sandbox addresses are reused. |
| Host-call cancellation | Delayed I/O, callback reentry and descendant work retain the original deadline, authority and reservation. Refund follows actual retirement or an explicit bounded ownership transfer; late completions cannot affect a new activation. |
| Currentness races | Revocation/retirement/policy replacement before the final start fence denies held readiness and cached code. An already accepted start follows the existing cutover rule, not a new implicit replay policy. |
| Reuse failure | Missing cleanup proof, partial teardown or a stuck guest produces quarantine without releasing still-owned resources. Check the next activation and fixed capacity rather than inspecting only a returned status. |
| Host-state restoration | On every success, trap and cancellation path, host TLS/register/signal state remains valid and unrelated worker tasks continue correctly. Test nesting and initialization failures before considering multithreaded guests. |

Start by destroying mutable sandbox state after every activation. A reset scheme
is a later optimization requiring its own proof and leakage tests; guest `free`
or `memset` is insufficient evidence. Immutable native-code sharing must also be
demonstrated for the selected relocation/mapping scheme rather than assumed.

## Benchmark design

Compare identical algorithms, inputs, observable results, capabilities and
lifecycle guarantees:

1. The current pinned LSF Wasmtime component path with its normal controls.
2. The candidate SFI path with verified final code, full isolation, fresh state,
   enforceable deadlines and complete cleanup.
3. An unrestricted native reference, clearly labeled as an uncontained lower
   bound rather than an eligible backend.

Measure cold compilation/rewriting/verification, image loading, first activation,
warm-code activation with fresh mutable state, compute-heavy work, a fixed
number of host calls, interruption and teardown separately. Separate cache hits
from initialization and code reuse from heap reuse. Report end-to-end latency
distributions, throughput at declared fixed capacity, CPU, binary size, virtual
address reservations, committed pages, RSS and memory retained after retirement.
Include the cost of denied operations and failed preparation.

Record compiler options, target features, engine settings, repetition/warm-up
policy and noise controls before interpreting results. Run the same functional
and negative controls for both eligible paths. Do not disable fuel/deadlines,
validation or fresh-state cleanup to manufacture comparability. A faster narrow
computation, an upstream SPEC number or a library-only call does not establish
an LSF latency or density improvement.

If only a small part of a request changes, report that fraction and the total
request effect. Do not generalize results to all six SDK profiles, transaction
workloads or opaque server APIs. Larger concurrency, profiling and soak runs
require an explicitly scoped campaign; this document authorizes none.

## Promotion decision

An ADR proposing production integration must provide:

- A mutually compatible, immutable toolchain/verifier/runtime bundle, its
  maintenance owner, licenses, reproducible build inputs and update policy.
- Exact supported platforms, artifact/ABI semantics, rejected features, threat
  model, trusted computing base and proof-to-implementation correspondence.
- Passing adversarial evidence for each claimed boundary, including actual
  interruption, fault containment, current authority and physical cleanup.
- Equivalent-workload measurements showing a worthwhile benefit over the
  maintained Wasmtime path, with the new startup and maintenance costs included.
- Explicit manifest/schema/admission and backend changes, fresh-state ownership,
  operator configuration, failure recovery and a fail-closed disable path.
  Existing T0/T1 names must not silently acquire different guarantees.

The decision may be to defer or reject the backend. If time-bounded retirement,
activation-only fault handling or complete read/write containment cannot be
established, do not promote in-process hostile execution. A bounded separate
execution-host design would require its own architecture and qualification.
Keep failed cases and raw results tied to their original source identities;
later documentation or source changes do not upgrade them into acceptance.
