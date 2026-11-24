# Recover a transaction and inspect deferred work

Use the Development operator CLI with an explicitly configured Phase 4 node.
Alpha.5 does not provide this transaction workflow. The node needs the protected
store, signed transaction companion, installed deployment and current namespace,
result-read and effect permissions described in
[installed transaction RPCs](../development/installed-transaction-rpc.md).
The six [transaction clients](../development/transaction-clients.md) expose the
same original-identity recovery boundary on their existing transports.

Current installed recovery remains a Development workflow with outstanding
complete terminal/pending native and packaged qualification. The
[installed recovery contract](../testing/installed-transaction-recovery.md)
describes native action inputs, original source identities, destination custody
and retained acceptance limits.

## Run a command once

Install the signed aggregate's `query` and `update` operations with their
configured routes. Create the namespace with the authorized operator and the
signed schema, then restart the node so it binds the installed operations to
that namespace.

```bash
latent --config "$OperatorConfig" --phase4 state create \
  --namespace "$Namespace" --incarnation "$Incarnation" \
  --authorization-publication "$Publication" --operation-id "$CreateOperation" \
  --expected-generation 0 --configuration "$NamespaceConfig"
```

From the invocation credential profile, read the current count and retain the
original key version if you intend to edit it. Keep the query budget read-only.

```bash
printf '%s\n' '[]' |
  latent --config "$InvokeConfig" --output json --phase4 transaction query \
    --service "$Service" --contract examples:transactional-aggregate/api@1.0.0 \
    --function query --route "$QueryRoute" --namespace "$Namespace" \
    --incarnation "$Incarnation" --input - --budget "$QueryBudget"
```

For this aggregate, the expected versions file is a JSON array with one entry
for the state key at `aggregate/count`. Base64-encode that key and put it in the
entry's `key` field. Decode the query payload's base64 `data` as JSON and encode its
original `key-version` byte array as base64 for the entry's `version` field.
If the query observed an absent key, set the entry's `absent` field to true and
omit `version`. Use one application-generated `ClientKey` for the edit and retain
the exact input and expected versions.

```bash
printf '%s\n' '[{"delta":1,"reject":false}]' |
  latent --config "$InvokeConfig" --output json --phase4 transaction invoke \
    --service "$Service" --contract examples:transactional-aggregate/api@1.0.0 \
    --function update --route "$CommandRoute" --namespace "$Namespace" \
    --incarnation "$Incarnation" --client-key "$ClientKey" \
    --expected-versions "$ExpectedVersions" --input - --budget "$CommandBudget"
```

For modest test fixtures, the query budget can set `cpuFuel` to 400000000,
`memoryBytes` to 67108864, `wallTimeLimitMillis` to 15000 and `stateReadBytes`
to 1048576. The command budget can add `stateWriteBytes` of 1048576 and
`effectCount` of 1. Keep both within the installed policy.
Take the commit receipt's `committedVersion.data` for a later query's
`--minimum-view-version`. If delivery fails, use the original key to recover
the command before choosing another edit.

## Preserve the original command

The [commit and recovery diagram](../assets/transaction-command-recovery.svg)
shows why the original command outcome and a deferred provider result must be
inspected independently. Its successful-commit path does not turn a lost reply,
unknown record or cancelled waiter into proof of an abort.

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

An explicit retry racing another identical retry may return that attempt's
original pending or terminal association after a definite claim conflict. It
still requires current result-read authority as well as command admission;
permission to submit does not imply permission to receive a retained result.
This bounded lookup neither starts another guest nor retries uncertain storage
I/O. Keep the original command, abort fence, retry request and fingerprint.

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

To see how an effect reached its current disposition, request one history page
with the same command and effect selectors:

```bash
latent --phase4 transaction effect-history \
  --namespace "$Namespace" --incarnation "$Incarnation" \
  --authorization-publication "$Publication" \
  --operation "$Operation" --client-key "$ClientKey" --effect-id "$EffectId" \
  --limit 16
```

For another page, supply the returned `nextCursor` as `--cursor` with the same
selectors. Only an absent cursor means the scan is complete. Each request checks
current authority, including when history contains an earlier uncertain attempt
followed by a broker acknowledgement. [Management paging](../protocol/state-management.md#command-commit-and-effect-inspection)

A browser uses the application's configured result route. Send a GET with the
original `Idempotency-Key` to recover the command. To check one of its effects,
send the same GET with the returned `Effect-Id` as well. The response exposes
the effect ID, disposition and dispatch attempt under current `inspect-effect`
permission. An unavailable result or a query that failed to return a view is
insufficient grounds for another edit. [Transaction HTTP](../development/transaction-http-v1.md#original-request-facts)

## Inspect unresolved effects before retiring a publication

With the node stopped, use the protected **transaction-recovery** command and
the original signed publication's current namespace-inspect grant. Set the outer
request's `publication` to that installed publication. The first request uses
this action.

```json
{"action":"inspect-publication-effects"}
```

Save the complete request to `Request` with your publication and use the
credential file provisioned for this offline operator.

```bash
latentd transaction-recovery --config "$NodeConfig" \
  --credential-file "$OfflineCredential" --tenant "$Tenant" \
  --request-file "$Request"
```


Each result lists at most 16 unresolved effects with their original command,
attempt, commit, binding, disposition and decoder profile. When `nextCursor`
is present, send it as `cursor` in the next request for the same publication.
A changed view, checkpoint generation or reviewed selection returns a
conflict. Start again at the current view before drawing a retirement decision.
Use each original effect's current status and separately authorized recovery
plan for any disposition change.

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
restore preserves the business incarnation, advances the recovery epoch and
keeps dispatch paused for explicit review. Acquire a fresh authorized view
before choosing a new edit. The original command key stays with its history.
Readiness does not override an operator's durable pause. Follow the
[protected checkpoint](../development/transaction-checkpoint.md),
[snapshot custody](../development/protected-snapshots.md) and
[state/effect retention rules](../architecture/state-and-effects.md#incoming-identity-formats-and-linked-retention).
The [container backup helper](local-storage-recovery.md) copies only its fixed
`config`, `data` and `cache` roots. It can omit an external checkpoint and its
receipt does not approve a transactional restore. The operator CLI commands
above expose inspection and effect management, not a general checkpoint/restore
workflow; those native and packaged acceptance requirements remain separate.
Code rollback cannot reverse an external action.
