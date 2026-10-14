# Activation commit protocol

Development implements this protocol through the explicit Phase 4 runtime.
The [stateless lifecycle](../activation-lifecycle.md) keeps its existing behavior:
a normal stateless invocation creates no durable business command. The selected
[transaction profile](transactions.md), signed companion, protected store and
current namespace authority are required for a transactional command.

The host owns commitment. A guest can stage bounded state changes and intents;
it cannot commit early, weaken atomicity or replace the selected storage backend.
[ADR-0062](../../adr/0062-host-own-serializable-transactions-and-durable-outcomes.md)
and the [state/effect architecture](../architecture/state-and-effects.md) define
the authoritative model. Collective and packaged acceptance remains separate.

## Inputs

The admitted command retains its authenticated tenant/caller, namespace
incarnation, operation, client key, canonical input fingerprint, optional entity,
stale-edit preconditions and explicit attempt identity. Its immutable completion
envelope binds staged writes, deferred intents, inbox acknowledgement when
present, and the original typed result or durable terminal disposition. All
formats and retained bytes have finite limits.

## Required behavior

```text
admit original command and acquire its consistent view
  -> execute the selected guest under the original deadline and authority
  -> retire accepted work and seal bounded staging
  -> validate final current authority, cancellation and serializable conflict fence
  -> atomically persist state, outbox, original outcome and linked inbox facts
  -> publish a currently authorized response or recover the original receipt
```

The actual engine must provide the selected atomic durability boundary. An
unsupported backend fails; this profile offers no implicit weaker-atomicity
fallback. Declared business rejection discards staged business writes and intents
while retaining the original terminal rejection. A fresh read-only query has no
command key, mutation interface or durable command/outbox obligation.

Immediate irreversible calls and unsupported synchronous child calls are denied
inside strict commands. Deferred dispatch has a separate lifetime and current
provider authority; commitment does not prove external acknowledgement.

## Recovery

Recover by the original command identity, not by inventing a new activation ID
or refreshing an edit precondition. Retained observations distinguish committed,
rejected, aborted, in-progress, unknown, expired and recovery-required outcomes.
Only actual host-issued durable abort evidence can authorize an explicitly chosen
new attempt under the retry contract. A timeout, cancelled wait, lost response or
expired payload supplies no such proof.

Use [transaction recovery](../operations/transaction-recovery.md) for the CLI
sequence and [authenticated management](state-management.md) for current caller
scope, publication selection and response ownership. Original command, attempt,
commit and effect associations remain intact across lookup.

## Output visibility

Success is published only after the promised durable command level and final
current result-read checks. Deferred effects may still be Pending or uncertain;
their durable intents and separately inspected delivery dispositions remain
linked to the original command. Durable workflow continuation is later Phase 6
work, not an implication of transaction completion.
