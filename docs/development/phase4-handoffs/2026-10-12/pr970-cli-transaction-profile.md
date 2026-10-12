# Explicit transaction CLI preparation

The current Java fixture's signed transaction package was refused by the ordinary
CLI before dispatch. `release publish-package` read the package with the
stateless manifest validator; transaction deployment preparation and deployment
reply projection selected that validator as well. This did not establish a
namespace/deployment readiness cycle because publication never reached the node.

The explicit global `--phase4` option selects the existing host compatibility
profile using `BudgetProfile::Phase4`, `PHASE4_HOST_ABI_V1`, and the canonical host
ABI digest. The selection reaches local capsule/deployment validation, local
package build/inspect/verify, signed package publication preparation, deployment
and rollout preparation, and deployment reply projection. Credentials, manifest
contents, and package markers do not select it. The default remains stateless;
the node's admission, current policy, publication, namespace, provider, runtime,
and execution checks remain independent. File/evidence/request ceilings and
managed-operation preconditions are unchanged.

Focused source validation on pinned Rust 1.97.1 passed all 162 CLI library tests
(158 original and four new cases), with no ignored tests. The new controls cover
explicit global argument selection, non-inference from a credential profile
named `phase4`, default transaction-budget refusal, exact managed preconditions
and tenant checks, and profile-aware lossless deployment projection with
unchanged identity rejection. Maintained CLI Clippy with all targets/features,
`--no-deps -- -D warnings`, passed. The CI suite retains every original required
case and adds these four; command coverage observes 88 baseline blocks, 282
current blocks, and 150 delegated owners.

Earlier private bootstrap attempts remain separate evidence: the first refused
the raw 484,946,056-byte AOT executable at the unchanged 256 MiB identity bound.
The second used a separately identified tuple with only nonallocated ELF debug
sections removed; the node started, but package preparation refused locally
with `requestDispatched=false`. Its actual stopped record reports physical
storage/native retirement, all owner/reservation/byte counters zero, and the
process reaped. The older Python retirement validator then rejected obsolete
DTO names; that collector correction has a separate owner.

These source controls do not qualify publication, the proposed management-only
namespace bootstrap sequence, signed Java execution, or the complete #718/#682
acceptance criteria. Those require a fresh, explicitly identified native tuple
and a separately retained actual campaign.
