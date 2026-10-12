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

The [bounded actual packet](pr970-cli-transaction-evidence.json) identifies the
committed CLI product and its separately copied debug-section transformation.
Default package inspection refuses the real transaction package; explicit
`--phase4` inspection succeeds without claiming trust or execution authority;
altering the component layer remains a local refusal. These controls use the
documented local-error exit 2. An earlier private control incorrectly expected
exit 1; that failed attempt is retained and supplies no passing evidence.

The real current legacy Java fixture also publishes once through the ordinary
CLI into a fresh node with empty configured operations, using explicit ephemeral
test trust. The native node and signer remain bound to their earlier `a37aa977`
source, the CLI to `ae3b0149`, the collector to `50594f0e`, and the Java capture to
`9bae8395`; this is a deliberately distinct-source diagnostic tuple. The
publication receipt reports committed admission, generation 1, and durable audit
acknowledgement 2. The node physically retires its storage/native owners and is
reaped. No guest invocation occurs.

The complete bootstrap sequence remains incomplete. The selected legacy
query-only inspection passes, but full legacy inspection refuses before any
policy, deployment, or namespace mutation. A timed read-only full inspection
returns permission denied in 1,729.603424 ms, below its unchanged 5,000 ms startup
deadline; the update-only control separately returns unavailable in
1,221.817493 ms. The HTTP adapter requires a 22,528-byte native response
reservation while the signed fixture retains the original 2,048-byte response
ceiling. The native owner must reconcile that envelope without silently
enlarging the original response/payload limits or treating an empty-operations
inspection as selected-source authority. Earlier generic aggregate and path
placement failures remain separate evidence.

The proposed management-only namespace bootstrap, signed Java execution, and
the complete #718/#682 acceptance criteria remain unqualified. The packet makes
no issue closure claim.
