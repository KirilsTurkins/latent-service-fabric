# Recover a transaction and inspect deferred work

Use the Development operator CLI with an explicitly configured Phase 4 node.
Alpha.5 does not provide this transaction workflow. The node needs the protected
store, signed transaction companion, installed deployment and current namespace,
result-read and effect permissions described in
[installed transaction RPCs](../development/installed-transaction-rpc.md).
The six [transaction clients](../development/transaction-clients.md) expose the
same original-identity recovery boundary on their existing transports.

This branch also describes PR #970's current installed recovery. That PR remains
pending integration and complete terminal/pending native qualification; it is
not a packaged-release acceptance record.

## Preserve the original command

Before dispatch, retain the original client key, operation, namespace incarnation,
canonical input bytes, entity and stale-edit preconditions. After response loss,
keep any validated command/attempt/transaction IDs and commit receipt. A local
timeout, cancelled future or disconnected HTTP stream leaves accepted work
uncertain until durable evidence establishes its outcome.

With your configured authenticated CLI, inspect the namespace and original key:

```bash
latent --phase4 state inspect \
  --namespace "$Namespace" --incarnation "$Incarnation" \
  --authorization-publication "$Publication"
latent --phase4 transaction lookup \
  --namespace "$Namespace" --incarnation "$Incarnation" \
  --authorization-publication "$Publication" \
  --operation "$Operation" --client-key "$ClientKey"
```

Use the actual installed authorization publication and original identity values.
If the command supplied an entity or approved shared recovery scope, preserve
those selectors with `--entity` or `--shared-recovery-scope`. An explicit
`--attempt-id` selects a real retained historical attempt; it does not create one.
Lookup reads the protected recovery lane without invoking the guest.

| Observation | Next step |
| --- | --- |
| Committed | Recover its original result or receipt. Obtain a new authorized query before choosing a new edit. |
| Rejected | Treat the business rejection as terminal for this command. Its staged writes and intents were discarded. |
| Aborted with a host-issued durable fence | Preserve that exact proof. A separate explicitly chosen new attempt must satisfy the original fingerprint and retry contract. |
| In progress, recovery required or unknown | Keep the original identity and restore the required connectivity/authority. Do not infer an abort or resubmit. |
| Expired result body | Inspect retained identity/receipt metadata where permitted. Expiry does not undo a commit or authorize another command. |

Lookup always requires current result-read authority. A namespace ID, retained
receipt or old publication is not a credential. Revocation or unavailable history
can prevent reading a result without proving that it never committed.

## Inspect the commit and effect separately

When an actual commit receipt or effect ID was returned, read it explicitly:

```bash
latent --phase4 transaction commit \
  --namespace "$Namespace" --incarnation "$Incarnation" \
  --authorization-publication "$Publication" \
  --operation "$Operation" --client-key "$ClientKey" --receipt-id "$ReceiptId"
latent --phase4 transaction effect \
  --namespace "$Namespace" --incarnation "$Incarnation" \
  --authorization-publication "$Publication" \
  --operation "$Operation" --client-key "$ClientKey" --effect-id "$EffectId"
```

Retain any original entity/shared scope selectors here too. The effect getter
checks the durable command/attempt/commit association and current `inspect-effect`
permission. It returns bounded metadata, not the payload or dispatch authority.
Command commitment and provider delivery are separate facts. A retained Pending
or uncertain effect does not become acknowledged because its delivery horizon
or the command's response body expired.

## Choose operator actions deliberately

`state plan-effect` prepares a checked redrive, reconcile or terminate plan with
the inspected record version, policy digest, original operation ID and reason.
`state apply-effect` submits its exact encoded plan once. After response loss,
`state effect-operation` reads that plan's original receipt. Follow the
[effect mutation contract](../development/effect-management-plans.md); preparing
a plan proves no mutation or provider acknowledgement. A browser or ordinary
application caller uses the authenticated
[transaction HTTP boundary](../development/transaction-http-v1.md), not private
management RPC or operator permissions.

For restore or retirement, preserve the coupled catalog/store/receipt history
and physically drain current owners before transferring custody. Older-history
restore changes incarnation and keeps dispatch paused for explicit review.
Readiness does not override an operator's durable pause. Use the
[backup guide](local-storage-recovery.md) and
[state/effect retention rules](../architecture/state-and-effects.md#incoming-identity-formats-and-linked-retention).
Code rollback cannot reverse an external action.
