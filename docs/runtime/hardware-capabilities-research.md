# Hardware-capability research

[Draft RFC-0008](../../rfcs/0008-native-guest-admission-and-activation-retirement.md)
covers possible native guest admission/retirement. Host-component and MPK
optimization studies retain their separate research scope.

Hardware capabilities are processor-enforced references with bounds and
permissions. LSF's research considers CHERI-like native compartments and other
hardware mechanisms for isolation and controlled sharing. **There is no LSF
CHERI backend, hardware-capability security profile or qualified hardware
execution path.** The track remains optional and cannot define the portable
capsule contract.

These memory references differ from the
[activation capability broker](capability-broker.md): the broker still decides
which installed operation an activation may perform under current policy and
budget. A hardware reference or sealed object does not grant tenant, HTTP,
storage or publication authority.

## Research directions and current behavior

The [research overview](../../research/hardware-capabilities/README.md)
distinguishes native guest compartments, isolating a narrow native host component,
a capability-aware Wasm engine, and an independent MPK pooling experiment.
None is enabled by a current manifest or node-profile name.

The delivered runtime uses [Wasmtime](wasmtime.md) and its current
[security profiles](execution-security-profiles.md). Pooling already has compact
configured reservations and zero configured guard bytes; upstream MPK savings
from a different layout cannot be assumed. MPK is not selected by the current
engine configuration. Virtual address space and resident memory are different
measurements.

The central research requirement is safe retirement before memory reuse:
protected bounds do not automatically expire every copied reference. Arena
reset, zeroing, hardware faults and client timeout are not cleanup proofs.
Outstanding buffers and callbacks retain ownership; a later activation must
not inherit access from an earlier one.

## Evidence and next work

The [upstream/platform review](../../research/hardware-capabilities/upstream-review.md)
separates CHERI, protection keys and memory tagging, reviews temporal-safety
research, and records platform limits. The
[evaluation plan](../../research/hardware-capabilities/evaluation-plan.md) defines
bounded compartment and MPK experiments, lifetime tests, sharing rules and
promotion gates. No new hardware measurements or native execution qualify those
proposals.

[Native-SFI](native-sfi-research.md) and
[call-graph fusion](call-graph-fusion-research.md) remain separate research tracks.
Hardware sharing may reduce copying without merging compartments, but it does
not supply their missing ABI, authority, failure or activation-lifecycle evidence.
