# Ordinary Go live stack and GC observations

This finite source programme advances #742 criterion 5 without claiming the
whole cost matrix. It compiles identical ordinary application source with the
existing default asynchronous profile and managed activation-v5 profile. It
uses the authenticated source94d normal27/native5 products and the node-stop
consumer's exact historical-source guard, with no host rebuild or normal27
repeat. Its execution remains pending until the dedicated actual lane passes.

The default-profile baseline and the managed-profile baseline expose bounded
`runtime.MemStats` and goroutine counts from actual fresh invocations. The
managed stack case keeps two ordinary goroutine stacks live across recursive
calls, channel suspension and actual GC. Each holds 33 complete 8192-byte
frames; checksums after release prove all frame contents survive. Before any
signed call, the pinned Go 1.27.2 Wasm compiler separately compiles that exact
ordinary recursive function and retains bounded escape/assembly diagnostics.
The pinned Wasm backend emits a 16,424-byte function frame: the original 8 KiB
array, its ordinary value-range checksum copy and 40 bytes of frame data. The
reader authenticates the actual SP-relative 8192-byte initialization at offset 40
and checksum copy at offset 8232 inside that function, with no heap escape;
unknown compiler output refuses. This is a compiler-reference layout check,
not a larger guest stack or memory limit.
That reference executes no application and alone is not final-component proof.
The signed case additionally requires StackInuse growth of at least 540672 bytes
for both live recursive stacks and NumGC growth before release. The heap case keeps a 12 MiB slice live
through GC, checks its touched pages and final byte, and calls KeepAlive after
the observations. HeapAlloc and NumGC must demonstrate the live work. A fresh
baseline follows each managed work case.

All six successful calls must retain the real published revision, known typed
result, reaped caller, original 1 billion fuel/64 MiB/120 second budget and zero
external effects. Existing node topology, quota, queue and cell observations
must show physical activation retirement after every call, followed by real
clean/reaped shutdown of both nodes. The original Task16/Executor2/Queue2/Wait4/
Timer2/Result2/Native2 profile remains unchanged. The evidence node's supported
audit queue64 is inherited from the node-stop consumer. There is no application
executor, explicit scheduler yield, new LSF observation facade or copied task
retirement policy.

Guest MemStats are source-owned measurements, not proof of complete physical
memory accounting or an independent stack hard ceiling. Per-call fuel, memory
and wall consumption remain the actual node result. This programme does not
establish minimum costs, throughput/fairness, hard GC bounds, exhaustion of the
whole original Task16 profile, or independent logical Executor/QueuedWork/
Result/Native exhaustion. The ordinary Go adapter does not directly allocate
several of those logical kinds. Its register audit currently marks HostCompleted
for both typed success and typed error, so that event cannot prove a successful
registration or a specific admission refusal. A generic trap is not substituted
for a typed per-bucket exhaustion witness. Those requirements, the remaining
mandatory runtime campaign rows and low-level networking remain open.

The first reference setup failure (module directly in the Go temporary root)
remains recorded. The corrected `3337` run then compiled the exact reference,
but its reader incorrectly expected symbolic `main.frame(SP)` syntax from the
Wasm backend. Its retained 36,853-byte compiler diagnostics now provide the
old-source failing control and exact concrete Wasm stack-layout fixture. Both
failures occurred before component compilation; neither qualifies signed costs.
The ordinary recursive source, both profiles, all six signed calls and runtime
budgets are unchanged by this reader correction.

The checked-in compiler diagnostic fixture removes only four trailing spaces
from the hexadecimal dump; every assembly/escape-analysis line is retained.
The full original diagnostic hash remains bound by the retained actual artifact.


The later205ce run passed the exact stack-reference parser and compiled,
packaged and signed the default-profile component. It stopped during deployment
setup before any cost invocation: that capsule imports the two clocks and random,
while the programme incorrectly added an activation grant. Native manifest
validation correctly rejects grants for contracts absent from the capsule.
The programme now retains the ordinary runtime-granted target for async-v1 and
installs the additional activation grant only for the explicitly selected v5
component. The actual programme-path control fails on the prior source and checks
both profiles without changing the six cases, their source, limits or host.
Corrected signed execution remains pending; these controls do not qualify costs.
