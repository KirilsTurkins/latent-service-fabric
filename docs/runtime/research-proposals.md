# Research proposals under review

The recent research contains concrete questions about execution semantics,
authority, persistence and resource ownership. Those fit the repository's
[RFC process](../../rfcs/README.md), alongside the underlying source/literature
studies. The four proposals below are **Draft**, with no accepted ADR or enabled
feature from this follow-up.

| Proposal | Decision requested | Research basis |
| --- | --- | --- |
| [RFC-0006: Durable workflow segments and continuation handoff](../../rfcs/0006-durable-workflow-segments-and-continuation-handoff.md) | Establish finite durable segments and a conditional checkpoint/wait/resume protocol before compiler capture. | [Continuation eviction](continuation-eviction-research.md). |
| [RFC-0007: Boundary-preserving local-call specialization](../../rfcs/0007-boundary-preserving-local-call-specialization.md) | Start with exact joint preparation while preserving child activation, authority, failure, budget and capacity boundaries. | [Call-graph fusion](call-graph-fusion-research.md). |
| [RFC-0008: Native guest admission and activation retirement](../../rfcs/0008-native-guest-admission-and-activation-retirement.md) | Separate native guest artifacts from trusted Wasmtime AOT and require qualified host entry, interruption and retirement. | [Native-SFI](native-sfi-research.md) and [hardware capabilities](hardware-capabilities-research.md). |
| [RFC-0009: Optional mapped state and fault ownership](../../rfcs/0009-optional-mapped-state-and-fault-ownership.md) | Make read-only mapped-image grants and fault retirement an explicit contract, distinct from existing async record reads. | [Userfault pager](userfault-pager-research.md). |

The workflow substrate is useful before a compiler frontend exists. Call
specialization deliberately retains current child Stores/cells first. Native-SFI
and hardware compartments share admission/lifecycle questions, so one RFC covers
that contract without choosing CHERI, LFI or a new public backend. MPK and narrow
host-library studies remain separate experiments. The pager proposal still needs
bounded unresolved-fault recovery before in-process promotion is credible.

Each draft contains alternatives, compatibility/resource/security/failure impact,
validation and open questions. Review can adopt, revise or defer the direction;
the corresponding decision belongs in a scoped ADR. Implemented interfaces and
conformance evidence are additional requirements for feature availability.
Existing accepted decisions and runtime behavior continue to apply.
