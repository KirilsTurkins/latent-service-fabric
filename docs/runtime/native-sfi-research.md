# Native-SFI research and current native execution

Native software fault isolation (native-SFI) is an exploratory optional backend
idea for executing restricted native machine code as a guest in the node's
address space. **LSF does not implement a native-SFI capsule backend.** There is
no native-SFI manifest selector, security profile or qualified execution path.

LSF already executes native instructions compiled from WebAssembly components.
That implemented path retains Wasmtime's Component Model and activation
semantics. Native-SFI would need a different artifact, verifier, loader and host
interface contract; it is not a new name for AOT compilation.

## Choose an existing path

| Goal | Current route |
| --- | --- |
| Run an LSF capsule | Use the [Wasmtime component runtime](wasmtime.md) with the selected [security profile](execution-security-profiles.md). |
| Prepare and reuse authenticated Wasmtime native output | Use [isolated trusted-local AOT](trusted-aot.md) where supported. It does not admit arbitrary ELF files or native libraries. |
| Use ordinary libraries or server APIs | Follow the [dependency compatibility rules](../component-development/library-compatibility.md) and [server-source model](../component-development/server-source.md). Compilation does not qualify their runtime behavior. |
| Evaluate a directly compiled native guest | Read the [native-SFI research track](../../research/native-sfi/README.md). Candidate code stays in a separate research harness until promotion requirements are met. |

## What the investigation must establish

A candidate must contain reads, writes, control transfers and privileged
operations; preserve typed calls and current activation capabilities; interrupt
code that never calls the host; and destroy mutable state before reuse. A
returned timeout or a signed native image does not prove those properties.
The existing [execution-cell lifecycle](../architecture/execution-cells.md)
remains the integration requirement.

The [pinned upstream review](../../research/native-sfi/upstream-review.md)
examines LFI, its compiler/verifier/runtime split and the limits of its formal
results and documented threat model. The
[evaluation plan](../../research/native-sfi/evaluation-plan.md) specifies native
artifact admission, adversarial observations, equivalent-workload benchmarks and
the promotion ADR. These are research requirements, not completed tests or
evidence of an LSF performance gain.

The current engine selection remains in the
[toolchain baseline](../development/toolchain.md#selected-versions). The
[research review's revision pins](../../research/native-sfi/README.md#repository-evidence-and-review-scope)
distinguish the supplied development snapshot from this documentation stack.
