# Blob model

Large payloads should not be repeatedly serialized through the router, runtime, and component call graph. LSF represents them as immutable content-addressed blob references.

## Write lifecycle

```text
begin staged write
  → bounded ranged writes
  → digest and size verification
  → seal immutable blob
  → issue activation-scoped lease
```

A failed or expired write session is reclaimable and cannot become visible as a valid blob reference.

## Read lifecycle

The capability broker grants a lease limited by tenant, activation, operation, byte budget, range, and expiration. Same-node implementations may use memory mapping or shared immutable regions; remote calls may transfer by digest. These choices cannot expose raw unrestricted host pointers to guest code.

## Ownership and retention

Blob identity is content digest plus tenant policy. Retention, pinning, replication, and garbage collection are platform concerns independent of capsule execution lifetime.
