# Hardware capabilities: primary evidence and platform limits

Reviewed on 2026-10-15. Source snapshots and published designs are not a tested
LSF hardware/software bundle. No toolchain, board, emulator, revoker or MPK
configuration was executed or benchmarked. Platform pages describe their state
at review time; they are not procurement or LSF compatibility evidence.

## Architecture and implementation sources

| Primary source | Reviewed material and scope |
| --- | --- |
| [CHERI project](https://www.cl.cam.ac.uk/research/security/ctsrd/cheri/) and [compartmentalization](https://www.cl.cam.ac.uk/research/security/ctsrd/cheri/cheri-compartmentalization.html) | Architectural capabilities complement virtual memory and support fine-grained software compartments. Software still constructs the compartments and their initial authority. |
| [CHERI specification `845c973538425c833e90cc38829985cd79d79658`](https://github.com/CTSRD-CHERI/cheri-specification/blob/845c973538425c833e90cc38829985cd79d79658/chap-intro.tex) | Tags, bounds, permissions, provenance, monotonic derivation and reachable capability authority. This document snapshot is not a proof of any selected CPU/OS/runtime combination. |
| [CHERIoT concepts](https://cheriot.org/book/concepts.html) and [compartments](https://cheriot.org/book/compartments.html) | Copy/delegation, bounds representability, sealed objects and checked compartment interfaces. Concrete CHERIoT APIs are not portable CHERI or LSF ABI definitions. |
| [Linux protection keys](https://docs.kernel.org/core-api/protection-keys.html) | x86 PKRU and Arm permission overlays, userspace rights changes and fault behavior. Thread-local permission state is not an activation identity. |
| [Linux Arm MTE interface](https://docs.kernel.org/arch/arm64/memory-tagging-extension.html) | Four-bit tags for 16-byte granules and synchronous/asynchronous/asymmetric fault modes. Matching tags are not unforgeable object authority. |
| [ERIM, USENIX Security 2019](https://www.usenix.org/system/files/sec19-vahldiek-oberwagner_0.pdf) | MPK isolation combined with controlled gates and binary inspection, including unsafe `WRPKRU` and `XRSTOR` instruction paths. It does not demonstrate LSF async worker, signal or cleanup integration. |
| [Wasmtime v48.0.6, `72bc45bd197c46718df0c02b8d4cbc1cb610ab2d`](https://github.com/bytecodealliance/wasmtime/tree/72bc45bd197c46718df0c02b8d4cbc1cb610ab2d) | [Pooling configuration](https://github.com/bytecodealliance/wasmtime/blob/72bc45bd197c46718df0c02b8d4cbc1cb610ab2d/crates/wasmtime/src/config.rs) and [feature declaration](https://github.com/bytecodealliance/wasmtime/blob/72bc45bd197c46718df0c02b8d4cbc1cb610ab2d/crates/wasmtime/Cargo.toml), rather than an unversioned API as evidence of LSF's selected default. |

## Mechanisms are not interchangeable

| Mechanism | Enforcement and important limit |
| --- | --- |
| CHERI | Protected, bounded references and permissions, with controlled code/object entry mechanisms. Broad roots or capabilities reachable through an exposed structure can confer more authority than intended. Ordinary capabilities are copyable; automatic lifetime revocation is not implied. |
| x86 MPK/PKU | Sixteen page-key values and thread-local data-access permissions; instruction fetch is not restricted. A secure native compartment must prevent unsafe rights-changing instructions and other bypass paths. This is not object-level pointer bounds. |
| Arm permission overlays | Eight page-key indexes with thread-local read/write/execute overlays in Linux's documented interface. User-writable permission state still needs a guarded runtime design; this is not CHERI reference integrity. |
| Arm MTE | Tag matching detects classes of memory misuse, with a small reusable tag space. Async fault delivery is distinct from synchronous access prevention. MTE configuration and tag manipulation cannot be left under arbitrary hostile-code control and called a complete sandbox. |

Sources: [CHERI specification](https://github.com/CTSRD-CHERI/cheri-specification/blob/845c973538425c833e90cc38829985cd79d79658/chap-intro.tex),
[Linux keys](https://docs.kernel.org/core-api/protection-keys.html),
[Linux MTE](https://docs.kernel.org/arch/arm64/memory-tagging-extension.html),
[ERIM](https://www.usenix.org/system/files/sec19-vahldiek-oberwagner_0.pdf).

Key counts constrain protection domains and active page groups, not the number
of deployed services. Any virtualization or reuse must show that retained worker
state and simultaneously accessible groups cannot expose another activation.

Bounds compression makes requested and actual bounds a research obligation.
Depending on range and alignment, a slice may not be exactly representable.
Check the resulting capability and reject or explicitly accommodate a private,
charged padded allocation; never silently include a neighbor's bytes.
[CHERIoT bounds discussion](https://cheriot.org/book/concepts.html).
Common compressed 64-bit-address designs use 128-bit capabilities plus tags;
this affects pointer-heavy layouts and alignment, not a universal doubling of
application memory. [CHERI bounds compression](https://www.cl.cam.ac.uk/research/security/ctsrd/cheri/cheri-concentrate/).

## Temporal safety and nested allocators

| Research | Result and limit |
| --- | --- |
| [Cornucopia Reloaded, ASPLOS 2024](https://www.cl.cam.ac.uk/research/security/ctsrd/pdfs/202404asplos-cornucopia-reloaded.pdf), [DOI](https://doi.org/10.1145/3620665.3640416) | Uses quarantine, sweeping revocation and capability-load barriers to reduce pauses. Freed storage is delayed until stale references cannot alias a reallocation. Its allocator/kernel/hardware assumptions do not establish an LSF activation-retirement bound. |
| [PoisonCap, arXiv 2605.13210v3, 29 September 2026](https://arxiv.org/html/2605.13210v3) | Proposes additional capability poisoning support for strict use-after-free and initialization safety, including nested allocators. Its evaluation uses emulation and an extended CHERI-Toooba FPGA implementation. These are extra ISA/software mechanisms, not a generic CHERI feature. |

PoisonCap distinguishes use-after-free from use-after-reallocation and discusses
allocators nested inside larger allocations. It also reports further robustness
engineering needed for its prototype revoker, including recursive-fault handling.
Treat the reviewed version as a preprint and preserve those limitations.
[Sections 2-4 and evaluation](https://arxiv.org/html/2605.13210v3).

**LSF implication:** a pool may reuse an activation slot without freeing its
parent allocation. An allocator's `free`-based guarantee therefore does not
automatically cover arena reset, suballocation reuse or virtual-address remapping.
The lifetime domain must match actual LSF reuse. Zeroing the new allocation can
prevent residual-data exposure but cannot by itself invalidate an old capability
that can write the new bytes. Define both reference retirement and initialization.

## Native compartment and sharing precedent

[CAP-VMs / Intravisor, arXiv 2202.05732v2](https://arxiv.org/html/2202.05732v2)
demonstrates capability-isolated native services, nested compartments and
controlled sharing through a trusted monitor. Its hybrid/native compatibility
and pure-capability goals have different granularity: a bounded legacy component
does not automatically have object-level safety throughout its internals.

The implementation uses a library OS, preallocated heap/stack regions and a
one-to-one mapping from requested guest threads to host threads. Those are
relevant integration assumptions, not LSF's fixed-cell or dormant-deployment
model. Reuse the mechanism as research evidence, not its entire lifecycle.
[Implementation and communication design](https://arxiv.org/html/2202.05732v2).

Read-only delegation also does not remove a writer's other aliases. A safe LSF
sharing experiment must freeze writers, retain allocation ownership and avoid
capability-bearing object graphs. Hardware sealing supplies protected object
references, not current HTTP/blob/service policy or unique ownership.
[CHERIoT compartment interfaces](https://cheriot.org/book/compartments.html).

## The existing Wasmtime MPK option

In the pinned 48.0.6 source, pooling's `memory_protection_keys` default is
`Enabled::No`. The API is experimental and describes key-based memory coloring
to remove guard regions, with runtime platform detection and distinct required,
automatic and disabled selections. Its feature enables `call-hook` for host
PKRU management.
[Configuration](https://github.com/bytecodealliance/wasmtime/blob/72bc45bd197c46718df0c02b8d4cbc1cb610ab2d/crates/wasmtime/src/config.rs),
[feature dependencies](https://github.com/bytecodealliance/wasmtime/blob/72bc45bd197c46718df0c02b8d4cbc1cb610ab2d/crates/wasmtime/Cargo.toml).

LSF does not select this API and already sets compact pooling reservations and
zero configured guard bytes. That does not prove MPK useless; it changes the
baseline. Measure actual generated bounds checks, transitions, mappings and
residency instead of importing upstream large-guard savings. Configured guard
values are not measurements of all allocator/OS overhead, and on-demand layout
is different. [LSF layout](../../crates/latent-wasmtime/src/config/layout.rs),
[engine composition](../../crates/latent-wasmtime/src/config/engine.rs).

MPK used inside Wasmtime is an optimization beneath the Wasm sandbox. It is not
permission to execute arbitrary native libraries. An MPK native compartment
needs its own instruction, syscall, gate and lifetime controls. Async migration,
callbacks, nested entry, faults and signals must preserve correct protection
state; an OS thread's key register is not an LSF activation owner.

## Platform status and portability

| Platform evidence at review time | Meaning for an experiment |
| --- | --- |
| [Arm Morello](https://www.arm.com/architecture/cpu/morello) | A prototype research board; Arm directs distribution to the CHERI Alliance and states it has no roadmap/plan to include Morello technology in current or future Arm products/architectures. Do not assume ordinary Arm hosts can enable it. |
| [Codasip Prime](https://codasip.com/solutions/riscv-processor-safety-security/cheri/codasip-prime/) | Describes an FPGA CHERI-RISC-V application processor, Linux demonstration image, C/C++ SDK/debugger and matching QEMU. This is an exploration stack, not proof of LSF's Rust, Wasmtime, native ABI or dependency compatibility. |
| [CHERIoT first ICENI silicon announcement, 4 March 2026](https://cheriot.org/silicon/2026/03/04/cheriot-first-silicon.html) and [programmer guide](https://cheriot.org/book/compartments.html) | Actual silicon is announced, with an ecosystem designed around microcontroller-class compartmentalization and an RTOS. Its controls are useful design references; the announcement does not qualify the Linux LSF node or imply a compatible server ABI. |
| [Morello architectural security report, UCAM-CL-TR-982](https://www.cl.cam.ac.uk/techreports/UCAM-CL-TR-982.pdf) | Explicitly excludes speculative/side-channel, Rowhammer and several physical attacks. Architectural memory protection must not be relabeled as those stronger guarantees. |

Choose one exact ISA, capability ABI, allocator/revoker, compiler, monitor and
OS stack for functional experiments. An emulator can test architectural behavior;
it cannot establish real cache, transition or revocation performance. FPGA,
prototype silicon and a different production CPU are separate measurement
populations. A pure-capability engine port, protecting native host code and
protecting guest-language objects remain distinct deliverables.
