# Diagnose provider failures and preserve recovery authority

## Outcome and supported scope

Identify which owner rejected or retained a capability operation, recover using
its actual operation identity, and stop the node without misreporting remote
effects or live resources as reclaimed. This development guide accompanies
[the real capability walkthrough](../learn/use-capabilities.md) and uses its
exact checkout, Linux x86_64 tools and temporary fixtures. For an installed node,
first use [authenticated readiness and configuration](../reference/standalone-node.md)
and the [native installation/upgrade procedure](../../packaging/linux/INSTALL.md).

The following references describe the complete executable configurations:
[standalone providers](../reference/standalone-providers.md),
[policy records](../runtime/capability-policies.md),
[compiled bindings](../runtime/capability-bindings.md) and
[shared pools](../runtime/provider-pools.md). There is no provider-discovery,
credential-fallback or configuration-reload API to substitute for these paths.

## Diagnose the boundary that actually failed

| Observation | Check and next action | What remains unknown or owned |
| --- | --- | --- |
| Invalid or unprotected configuration | Run `latentd check-config --config` on the intended protected file; inspect the bounded diagnostic and the closed schema before starting. Unknown provider fields and unsafe credential files fail closed. | A successful check does not establish catalog recovery, a live listener or execution permission. |
| Authentication or grant denial | Preserve the activation/operation identity. Check tenant, selected publication/revision, deployment grant, current policy generation, exact binding and actual installed provider descriptor. The walkthrough demonstrates allowed/denied `capability explain` and post-revocation invocation. | Local package verification and a diagnostic explanation are not a reusable grant. A principal cannot gain authority by setting metadata. |
| Exhausted budget or saturated pool | Compare the original deadline and remaining request/byte/descendant allowance with active broker, pool and I/O inventory. Release owned chunks/handles when the application has finished with them. | Queued work, sleeping host calls, active descendants and delayed consumers still hold real capacity. Raising a caller limit does not raise the node/provider ceiling. |
| Slow, disconnected or unavailable provider | Determine whether dispatch occurred. Use the protocol's returned operation/receipt identity and its own recovery procedure. Keep the original deadline; inspect retained cleanup work before replacing the provider. | A lost reply, timeout or cancellation after possible dispatch cannot establish that the remote effect did not happen. |
| Stale credential/provider generation | Install/rotate through the trusted adapter with the expected epoch. An old leased generation remains charged until its actual users release it. Reject new calls using stale authority. | Replacing configuration does not retroactively undo remote work or immediately reclaim every connection. |
| Shutdown reports incomplete cleanup | Preserve the failure record and inventory. Wait only within the configured grace/deadline, then follow the owning runner or service-manager stop procedure and verify process reap. | A cancelled caller future is not proof that its physical socket, child process, buffer or provider upload was reclaimed. |

The [audit/inspection contract](../runtime/capability-audit.md) distinguishes
required provider attempts and typed outcomes from optional telemetry. Use scoped,
bounded reads through the authenticated CLI described in
[the command reference](../reference/operator-cli.md). Do not publish arbitrary
provider logs, credential selectors, authorization headers or secret payloads.
Record configuration/profile identities, activation and operation IDs, observed
outcomes and cleanup counters instead.

## Reproduce wrong authority, exhaustion and provider failure

Run the standalone workflow in [Use capabilities](../learn/use-capabilities.md)
for wrong-path denial and grant revocation. Its exact peer request count and
clean shutdown assertions distinguish rejection from a hidden dispatch/retry.
Then use the following maintained cases with the same pinned source:

```bash
cargo test --locked -p latent-wasmtime --test http \
  --test streaming_http --test local_secrets --test random --test metrics -- --nocapture
cargo test --locked -p latent-capabilities --lib broker::pools -- --nocapture
```

Inspect the named results: exhausted original request budgets, cancelled stream
reads, failed secret reload preserving the current value, failed entropy without
partial bytes, and a closed metric exporter returning typed unavailability.
The pool regressions retain old credential epochs while requests are live and
verify finite cleanup under contention. These are deliberately induced failures
whose **expected typed outcome and cleanup** make the tests pass. A crashing,
ignored or empty target is not equivalent.

The [S3/Vault/NATS walkthrough](exercise-provider-failure-and-recovery.md)
extends this to actual disposable TLS services: wrong credentials and immutable
range verification, interrupted multipart work, Vault version/rotation/revocation,
and NATS lost acknowledgements plus trigger overload/redelivery. Each runner
removes only the service it owns. No paid account or pre-existing container is
used. Inspect its retained source/lock identity before comparing old results to
a changed provider or dependency graph.

## Recover immediate effects without manufacturing certainty

HTTP response delivery, S3 publication acknowledgement and a NATS broker receipt
are protocol observations. They do not establish downstream application success.
Follow the [immediate-operation semantics](../runtime/capabilities.md#phase-3-immediate-provider-operations):
rejection before dispatch, acknowledgement, known failure and uncertainty after
possible dispatch are different outcomes. Do not turn uncertainty into a fresh
unconditional mutation, even when a generic client can retry transport requests.

NATS consumer triggers preserve bounded delivered-message and acknowledgement
ownership. Redelivery can follow an uncertain acknowledgement; consumer processing
must respect the protocol's identity and deduplication scope. The current
implementation is not a transactional outbox or exactly-once application workflow.
Similarly, a sealed immutable blob is not an application-state commit.

For node management, preserve the operation ID and expected generation/revision,
then query the matching retained receipt before deciding on recovery. Receipt
retention is bounded, so absence is not proof that the mutation never ran. Follow
[publication authority](../reference/publication-api.md) and
[rollout/recovery](../phase-2-operator-workflows.md), not a blanket retry recipe.

## Select a security profile deliberately

| Profile | Supported boundary | Required operator decision |
| --- | --- | --- |
| `local-experimental-v1` | T0 operator-controlled workloads/preparation | Use only the local experimental trust assumptions. Installing an HTTP provider does not upgrade this boundary. |
| `external-capsule-v1` | T1 hostile component bytes/inputs with a trusted node, Wasmtime, host bindings, native loader and OS | Enforced package admission, protected trust/credential/native-key files, exact approved ABI and supported Linux x86_64 isolated compilation are all required. |
| T2/T3 or strong side-channel/process-compromise isolation | Unsupported | Do not infer these guarantees from signatures, fresh Wasm stores, an isolated compiler or a passing test. |

Read [execution profiles](../runtime/execution-security-profiles.md),
[protected configuration](../runtime/protected-configuration.md) and
[isolated AOT](../runtime/trusted-aot.md) before changing a deployed profile.
`check-config` probes the actual compiler and approved executable digest but
compiles no component and grants no reusable native-loading proof. Each real job
rechecks its source, authority and bounded readiness. There is no fallback to
in-process compilation when the selected external-profile compiler fails.

The external-profile catalog marker prevents an ordinary restart under a weaker
profile. Keep it with the catalog, admission generation and clock floor in a
verified complete backup. Do not delete a corrupt marker or downgrade the binary
to bypass recovery rules; binary downgrade does not reverse storage migration.
Native-cache authentication and compatibility checks do not replace current
publication/grant checks.

OCI registry credentials, provider credentials and guest secrets have distinct
owners. Follow [registry networking](../reference/oci-network-profile.md) for
authentication, DNS and redirect restrictions, and the provider's own network
policy for capability calls. Never forward a registry token or backend provider
credential into browser code, guest metadata, copied examples or public receipts.

## Record verification and clean up

Retain the exact source, dependency lock, selected test names, executable/package
hashes, expected failure outcomes and owned cleanup. Machine-readable receipts
must keep their original identities. Configured limits are not measured capacity,
and a bounded fixture is not production or hostile-multitenant certification.
The [maintained security monitoring guide](../operations/maintained-security-monitoring.md)
assigns advisory/lock/workflow review to its existing owners; a manual scan cannot
be relabelled as a scheduled run.

The companion runners and tests close their own temporary nodes, services,
children and storage. Preserve their public receipts for review, then remove only
their explicitly owned review directories. Installed data, unrelated containers
and operator credentials are outside that cleanup. A maintainer walkthrough of
the rendered guides remains a separate coverage-review requirement.
