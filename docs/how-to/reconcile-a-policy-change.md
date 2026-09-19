# Reconcile a policy change without restoring revoked authority

## Outcome and supported boundary

Use the real management CLI and a separate local node to apply a policy once,
inspect a bounded page, explain a denial, revoke the policy, recover the original
operation receipt and restart without restoring revoked authority. This is the
control-plane portion of [#359](https://github.com/KirilsTurkins/latent-service-fabric/issues/359).
It executes **zero guest invocations** and is not provider-backed authorization,
provider failure/overload, secret access or a six-client transport qualification.

The actual source is [the maintained policy workflow](../../tools/run_capability_policy_workflow.py),
the [bounded subprocess owner](../../tools/phase2_operator_process.py), the
[node lifecycle helper](../../tools/phase2_operator_scenario.py) and the
[operator CLI reference](../reference/operator-cli.md).
Its fixture uses an empty policy and synthetic provider-binding identity so that
explanation denies. It does not install a real provider or grant an application
secret access. Do not copy those synthetic policy/configuration identities into
an operator deployment.

## Prerequisites and version

Use the same clean reviewed Linux source and paired CLI/node as the
[delivery walkthrough](../learn/deliver-and-recover-a-capsule.md).
Python 3.13.5 and the pinned Rust toolchain are the contributor profile. No Docker
or external provider is needed for this particular workflow. The script creates
only private test configuration, protected explicit test credentials and one
ephemeral loopback listener; it neither installs systemd nor changes `/etc`.

For a real installation, use independently publisher-authenticated native
binaries and an operator-provisioned protected client config. Reading a policy,
possessing a configuration file or verifying a package never grants execution
authority. The broker still applies the actual tenant/publication/import/grant/
provider restrictions and handle lifetime at execution time; see
[identity and capabilities](../architecture/identity-and-capabilities.md) and
[provider pools](../runtime/provider-pools.md).

## Run the controlled real-node walkthrough

From the clean repository root, after the paired source build:

```bash
set -euo pipefail
umask 077
test -z "$(git status --porcelain=v1 --untracked-files=normal)"
export CARGO_TARGET_DIR="$PWD/target"
POLICY_REVIEW=$(mktemp -d "${TMPDIR:-/tmp}/latent-policy-guide.XXXXXXXX")
timeout --kill-after=15s 180s python3 tools/run_capability_policy_workflow.py \
  --node "$CARGO_TARGET_DIR/debug/latentd" \
  --cli "$CARGO_TARGET_DIR/debug/latent" > "$POLICY_REVIEW/receipt.json"
```

The script bounds useful work to 120 seconds, with separate owned cleanup, and
starts the node twice using the same retained data. It uses real Protobuf RPCs
through the CLI, not a fake client. Its synthetic credentials stay in private
files and are never a production default or an operator credential to share.

The receipt schema is `latent.capability-policy.workflow.v1`. The
[recorded real run](../evidence/core-operator-walkthrough-35454985599.json) reports
`passed:true`, 15 CLI calls, two node starts, `guestInvokes:0`, replayed revision
`"2"`, recovered revocation `"4"` and `ownersReaped:true`.
Those revisions belong to that new test node; never use them as guessed
preconditions against an existing node.

## Follow the operation and authority identities

| Step in the complete source | Observation and why it matters |
| --- | --- |
| Apply empty policy `p` with operation `create-p` and expected generation `0` | The first result is retained. Repeating the exact identified request returns the same result, not a second mutation. This controlled reconciliation is not a universal retry recommendation. |
| Get policy `p`; add the synthetic binding with its own operation | Read results preserve the distinct policy/binding records. A binding/configuration identity is not a secret, provider handle or execution grant. |
| Explain a read request under the empty policy | The result is `deny` and `executionPermission:false`. Explanation is a control-plane observation; it neither invokes a guest nor fetches a secret. |
| List with `--page-size 1` | The expected single policy is returned with no next token. Page bounds are explicit; never silently traverse an unbounded collection. |
| Revoke `p` with operation `revoke-p` and the observed expected generation | The resulting receipt records the new revoked revision. Read it by the same operation ID and tenant rather than manufacturing another ID after uncertainty. |
| Reconcile the original `create-p` operation again | Its historical receipt still describes the old revision, while a fresh get still reports the policy revoked. Returning an old receipt does **not** resurrect authority. |
| Query a deliberately absent operation | `outcomeKnown:false` and `mutationOutcome:"unknown"` remain unknown. Missing retention is not proof that an action never happened. |
| Stop and restart the same node, then read again | The revocation and its exact receipt survive. Final shutdown reports no active policy jobs or retained read owners, and both node processes are reaped. |

For an operator's own request, retain the chosen operation ID and returned
generation/state precondition before advancing the workflow. Do not borrow a
receipt from another tenant, replace a rejected precondition with the latest
value automatically, or reinterpret a historical reply as current authority.
Immutable policy/configuration identities and bounded handle lifetimes remain
independent of whether a caller can still read a historical receipt.

## Failure and recovery

| Observation | Safe response |
| --- | --- |
| Wrong protected client config/tenant | Inspect the selected profile, role and private file permissions. Never print or paste the credential or widen the loopback listener. |
| Expected-generation conflict | Read current policy and the original operation receipt under the same tenant; obtain an explicit new decision. Do not guess a fresh precondition and retry a mutation. |
| RPC timeout, cancellation or connection loss | Keep the original operation identity. Inspect its retained receipt/status; an unknown lookup is still uncertain and does not authorize repeating external work. |
| Explain denies despite a configuration file being present | Inspect the actual policy intersection and selected binding identity. A config file or local package verification is not execution permission. |
| Replaying creation makes a revoked policy active | Treat this as a regression and stop. Do not normalize the test by issuing an extra revoke before checking current authority. |
| Restart loses the revoked record or cleanup has active owners | Preserve the redacted failed receipt; stop only the owned node processes. A fresh database or republished policy would hide the failure. |

Audit records describe observations; they do not prove a provider side effect is
durably committed. The control-plane example makes no external provider call.
Cancellation acknowledgement, descendant-budget conservation, backpressure,
provider credentials/rotation and actual allowed/denied guest behavior need their
own provider/client harnesses. See [capabilities](../runtime/capabilities.md),
[resource budgets](../runtime/resource-budgets.md),
[security profiles](../runtime/execution-security-profiles.md) and
[security monitoring](../operations/maintained-security-monitoring.md).

## Cleanup and validation level

The maintained runner removes its own private node/client configuration and
state after clean bounded shutdown. Retain only the small receipt in the newly
created `POLICY_REVIEW` directory; remove only that verified directory after
review. Do not delete another worktree, any installed node state, user containers
or a retained production credential/trust file.

This guide consumes the successful `Validate capability policy CLI lifecycle`
step in CI run `35454985599`. Its runtime checkout is `05360c50`, distinct from
the reviewed PR head `edec84fa`; the evidence records that distinction and the
redacted log receipt. Command/source checks are a fresh guide-validation layer,
not a new guest/provider run. The site's rendered newcomer review remains
[pending alongside the other child-guide outcomes](../development/operator-guide-acceptance.md).
