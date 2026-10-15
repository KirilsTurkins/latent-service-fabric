# Hardware capability backends

Investigate CHERI-like bounded capabilities and other hardware compartment
mechanisms for fine-grained native isolation. **This track must remain optional
and cannot define the portable capsule contract.**

**Status: source/literature review and experiment design only.** There is no LSF
CHERI backend, hardware-capability prototype, platform qualification or measured
hardware speedup. No hardware, emulator or MPK experiment was run for this review.
The [research policy](../README.md) requires semantics, portability, security
analysis, benchmarks and a promotion ADR before adoption.

Read the [upstream and platform review](upstream-review.md) for primary evidence
and its limits, and the [evaluation plan](evaluation-plan.md) for authority,
retirement, sharing and measurement gates. The website's
[hardware-capabilities guide](../../docs/runtime/hardware-capabilities-research.md)
explains current availability.

## Reviewed LSF source

Reviewed on 2026-10-15 against documentation-stack parent
[`26358106aceec0a0da675ff385f844cad6e5fd10`](https://github.com/KirilsTurkins/latent-service-fabric/tree/26358106aceec0a0da675ff385f844cad6e5fd10).
The supplied development snapshot
[`90cf1f4c87ca24e9a64b077dc2eb501dcef22441`](https://github.com/KirilsTurkins/latent-service-fabric/tree/90cf1f4c87ca24e9a64b077dc2eb501dcef22441)
was checked separately. It selects Wasmtime 48.0.5; this stack selects 48.0.6.
Its pooling layout values agree with the reviewed stack, but engine/profile
identities and execution evidence are not interchangeable.

| Finding | Source and scope |
| --- | --- |
| The track previously contained only its charter. | [Track at the reviewed parent](https://github.com/KirilsTurkins/latent-service-fabric/blob/26358106aceec0a0da675ff385f844cad6e5fd10/research/hardware-capabilities/README.md). This update adds analysis, not an executable backend. |
| No hardware-capability execution selector exists. | [Manifest backend enum](../../crates/latent-manifest/src/lib.rs) and [isolation profiles](../../crates/latent-wasmtime/src/config/isolation.rs). `external-capsule-v1` requires the selected Linux x86_64 Wasmtime boundary, not CHERI. |
| Pooling has a compact configured layout. | [Memory layout](../../crates/latent-wasmtime/src/config/layout.rs): reservation equals `maximum_memory_bytes`, growth reservation is zero and configured guard bytes are zero. On-demand allocation has different values. These setters are not total virtual-memory or RSS measurements. |
| MPK is not selected by the current engine composition. | [Workspace features](../../Cargo.toml) do not request `memory-protection-keys`; [engine pooling setup](../../crates/latent-wasmtime/src/config/engine.rs) does not enable it. The pinned upstream default is off; see the [upstream review](upstream-review.md#the-existing-wasmtime-mpk-option). |
| Application authority and physical ownership already have software owners. | [Broker plans](../../crates/latent-capabilities/src/broker/plan.rs), [executor cleanup](../../crates/latent-executor/src/lib.rs) and [execution cells](../../docs/architecture/execution-cells.md). Hardware references cannot replace current policy, original ledgers or cleanup proofs. |

## Three different meanings of capability

An LSF capability authorizes a checked operation under an activation's identity,
current policy, provider installation and budget. A CHERI architectural
capability is a protected reference carrying memory bounds and permissions. An
affine LSF owner conserves a particular reservation or cleanup obligation. These
are related tools, not interchangeable objects.

CHERI tags protect reference integrity; permitted derivation can narrow
authority rather than invent it. Capabilities can generally be copied, so they
do not automatically supply unique ownership or expiry. The processor enforces
the authority software hands out, not tenant policy or publication eligibility.
[CHERI specification](https://github.com/CTSRD-CHERI/cheri-specification/blob/845c973538425c833e90cc38829985cd79d79658/chap-intro.tex),
[CHERIoT capability concepts](https://cheriot.org/book/concepts.html).

A useful design would use hardware to prevent bypass of a narrow host entry,
while the existing broker decides whether that operation may start. A sealed
resource or code entry is not permanent permission, a one-use token or proof of
the caller's LSF identity. The trusted entry still checks type, activation,
generation, authority and resource ownership.

## Separate research directions

| Direction | Question and first scope |
| --- | --- |
| Native capsule compartment | Can a selected capability ISA, loader and monitor isolate native guest memory, entrypoints and execution while preserving LSF activation semantics? A new backend/ABI needs independent qualification. |
| Narrow native host component | Can one parser or codec operate with only bounded input, output and an activation-owned arena? This is the preferred first compartment study, with an explicit hostile-component model and small trusted monitor. It does not qualify the whole node. |
| Capability-aware Wasm engine | Could a port retain the portable component contract while protecting the engine or guest linear-memory boundary? Engine portability, host implementation safety and object safety inside guest linear memory are separate goals. |
| MPK-assisted current Wasmtime pooling | Is there a measured layout/transition benefit over LSF's already compact pooling settings? This is an independent x86_64 performance experiment, not a CHERI or native-capsule backend. |

[Native-SFI](../native-sfi/README.md) studies restricted native instruction
streams; [fusion](../call-graph-fusion/README.md) studies call composition and
logical boundaries. Hardware-assisted sharing might make controlled interaction
cheaper without merging compartments, but none of these tracks supplies another
track's admission, authority or lifetime proof.

## Retirement is the decisive boundary

Bounds restrict where a reference can access memory, not automatically when its
allocation stops belonging to a principal. Clearing bytes, changing a software
generation, resetting an arena or remapping the same address does not establish
that all old direct memory capabilities have become unusable.

Define two claims separately: denying access immediately after `free`, and
preventing a stale reference from accessing a later allocation. LSF must at
least protect a subsequent activation and preserve its ownership boundaries;
strict per-object use-after-free protection is an additional declared guarantee,
not something to infer from a generic CHERI label. The
[temporal-safety literature](upstream-review.md#temporal-safety-and-nested-allocators)
uses different mechanisms and assumptions for these claims.

Activation-scoped arenas with enforced non-escape may simplify reclamation. That
requires proof covering registers, stacks, host-held references, callbacks,
child results and accepted provider work. If references escape, either revoke
their authority or retain their regions under explicit bounded owners until
they cannot reach reused storage. A generation check at a host gate does not
invalidate a direct memory capability that bypasses that gate.

Allocator quarantine and `ExecutionCleanup::Quarantine` are different mechanisms:
the former delays memory reuse, the latter denies cell reuse. Neither proves
that the other has completed. Still-live memory, revocation work and callbacks
must remain charged. There is no refund merely because the client stops waiting.

## Sharing and portability constraints

Passing B a read-only view of A's bytes does not make those bytes immutable if A
retains a writable alias. Sharing also retains an allocation owner and may expose
further authority through capabilities embedded in the object. Start with
capability-free byte regions, checked actual bounds and a frozen writer state;
do not expose arbitrary host structures or mutable object graphs.

The [current local-call interface](../../docs/runtime/local-service-invocation.md)
has observable byte/value and failure semantics. A native capability is not a
portable WIT/JSON/protobuf pointer representation. Hardware sharing needs a
qualified adapter and lifetime contract; it cannot silently replace that API,
merge budgets or grant another service's authority.

No hardware mechanism alone supplies instruction/time budgets, safe fault
recovery, bounded language initialization, listener-free server semantics,
transaction atomicity or a stronger kernel/side-channel profile. Maintain the
[current security-profile limits](../../docs/runtime/execution-security-profiles.md).
Morello, CHERI-RISC-V and CHERIoT have different ISAs, ABIs and software stacks;
none is an already qualified LSF target. See the
[platform review](upstream-review.md#platform-status-and-portability).

The next useful result is a bounded compartment/retirement study and a separate
MPK baseline investigation, followed by an explicit promotion or deferral
decision. Missing required hardware must not silently downgrade a selected
security requirement or change the portable capsule contract.
