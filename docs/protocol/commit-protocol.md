# Activation commit protocol

The commit coordinator is the semantic boundary between guest completion and externally durable success.

## Inputs

An activation commit plan contains:

- activation identity,
- optional state transaction,
- zero or more effect intents,
- output digest or result metadata,
- audit and trace metadata.

## Required behavior

```text
PREPARING_COMMIT
  → validate transaction read set
  → persist state mutations and effect outbox records atomically
  → create durable commit receipt
  → COMMITTED
```

If the selected backend cannot atomically persist state and effect intents, the deployment must opt into weaker semantics explicitly or use a coordinator/backend combination that can.

## Recovery

Commit inspection by activation ID must distinguish unknown, preparing, committed, aborted, and recovery-required states. A lost client response after commit is resolved by inspection rather than blind re-execution.

## Output visibility

The invocation response may be returned only after the platform has reached the contractually promised commit level. Deferred external effects may still be pending after a successful response, but their intents are durable.
