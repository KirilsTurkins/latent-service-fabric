# ADR-0028: Retain activation ownership across asynchronous waits

- **Status:** Accepted
- **Date:** 2026-09-13
- **Follow-up to:** [ADR-0006](0006-use-reusable-generic-execution-cells.md)

## Context

ADR-0006 makes execution cells fixed node-owned resources that are leased to active
work and reset before reuse. Phase 1 implemented fresh Wasmtime stores, affine
cell leases, bounded scheduling and affirmative cleanup. Phase 3 introduces
asynchronous providers and isolated-local descendant calls. Both can yield the
shared runtime thread while the activation still owns guest and host resources.

A yielded future is therefore not the same thing as a dormant service or a freed
cell. Treating an `await` as a refund would permit a second activation to reuse a
cell while the first activation still owns its Store, guest memory, host handles,
provider buffers or descendant reservations. Conversely, keeping every parent
cell occupied while descendants wait for the same fixed pool can deadlock if all
compatible cells are held by ancestors.

This decision makes those ownership and progress rules explicit without adding a
new execution backend, durable suspension, stack checkpointing or per-service
workers.

## Decision

An activation remains active across asynchronous provider and descendant waits.
Yielding to the node's shared async runtime releases only the current poller's
execution time. It does not implicitly release or reset any activation resource.

While an activation is waiting, its public lifecycle phase remains `Running`.
`WaitingProvider`, `WaitingDescendant` and `Cleaning` are architectural ownership
states, not new wire-visible lifecycle phases.

The following ownership rules are normative:

| Retained resource | Owner while waiting | Retirement rule |
| --- | --- | --- |
| execution-cell lease and admission concurrency reservation | parent activation execution owner | positive backend cleanup plus pool release, or conservative quarantine |
| Wasmtime Store, instance, guest memory and activation-local host bindings | parent activation execution owner | drop/reset only after guest execution can no longer resume or re-enter |
| activation budget, deadline and cancellation registration | activation lifecycle owner | final accounting after cell and descendant/provider ownership settles |
| provider call/stream permit, staged bytes and response buffers | bounded provider-operation owner under the activation | actual completion/cancellation cleanup, or an explicit safe ownership transfer defined by #205 |
| descendant budget/admission reservation | parent cancellation/budget tree defined by #208 | accepted child retirement or failed admission, exactly once |
| accepted child cell, Store and host bindings | child activation owner | the same affirmative cleanup/quarantine rules as any activation |
| disconnect/timeout cleanup continuation | bounded node cleanup supervisor | completion or conservative quarantine at its finite cap |

A timeout used by a test or supervisor is a watchdog. Expiration can prove that a
bound was exceeded; it does not prove that a provider stopped, a child retired,
a cell was cleaned or a reservation was refunded.

## Supported wait transitions

The allowed ownership transitions are:

```text
Running
  -> WaitingProvider -> Running
  -> WaitingDescendant -> Running
  -> Cleaning -> Released
                    \-> Quarantined

WaitingProvider   -> Cleaning
WaitingDescendant -> Cleaning
```

Entering either waiting state keeps the parent cell, Store, memory, bindings,
budget and cancellation identity live. The activation is not converted into a
dormant deployment, and LSF does not serialize its stack or preserve a warmed
instance for later tenant reuse.

A downstream provider may define a safe transfer that lets operation cleanup
continue after the guest can no longer observe it. Such a transfer is valid only
when it is affine and bounded, severs every reference to the cell, Store, guest
memory and activation-local handles, moves all still-live permits and buffers to
a node-owned cleanup owner, and keeps resource charges until physical retirement.
Until #205 implements and validates such a transition for a provider, the
conservative rule is to retain the activation's cleanup ownership and withhold
cell reuse.

## Descendant calls and fixed-capacity progress

An isolated-local child is a separate activation with a fresh Store and a normal
scheduler assignment. The parent does not free or loan its cell merely because
it awaits that child.

Before a child call is allowed to block its parent, #209 must establish one of two
bounded outcomes using the fixed declared node capacity:

1. progress is possible under an explicit bounded allocation/reservation policy,
   with every reserved unit charged to the call tree; or
2. the child call is rejected promptly with a finite resource/backpressure
   outcome.

The implementation may choose the exact reservation algorithm, but it may not
create unbounded workers, hidden cells, per-service executors or capacity outside
the configured pool. It may not wait indefinitely for capacity held entirely by
its own ancestor chain, and it may not manufacture progress by refunding the
parent's still-live cell or budget.

Ordinary scheduler fairness remains applicable to independent work. Descendant
progress is an additional admission constraint because a fair queue alone cannot
break a circular wait when every compatible cell is retained by waiting parents.

## Descendant budgets and cancellation

#208 owns the conserved descendant budget and cancellation-tree implementation.
This decision requires that implementation to preserve the following rules:

- child identity and authority are host-derived, not trusted from guest-supplied
  parent/root metadata;
- child absolute deadline is no later than its parent and fuel, I/O, call, memory,
  depth/fan-out and live-descendant limits are conserved through non-forgeable
  reservations;
- reservation occurs before child admission, and accepted child work remains
  charged until actual child retirement;
- child admission failure returns only the unused reservation exactly once;
- parent cancellation closes future delegation and propagates to linked live
  children, but cancellation acceptance is not proof that child/provider cleanup
  completed;
- parent completion or a dropped awaiter cannot refund a still-running child;
- late provider/child completion settles against its existing owner exactly once
  and cannot re-enter a completed parent or mint a second refund.

There is no detached durable-child mode in this phase. If a caller disappears,
existing bounded cleanup supervision retains the activation and its descendants
until their ownership is reconciled or the affected cell is conservatively
quarantined.

## Validation ownership

The implementation tickets retain their existing scopes:

- #205 tests delayed provider completion, retained buffers/permits, cancellation
  and stream cleanup without early cell reuse;
- #208 tests conserved simultaneous descendant reservations, cancellation trees,
  admission failures and late completion without double release;
- #209 tests all-cells-occupied nested calls, bounded depth/concurrency and the
  progress-or-prompt-rejection rule using real components;
- #238 integrates deterministic saturation, cancellation and cleanup schedules
  across the delivered providers and child-call path.

Tests should use controlled rendezvous and observable ownership counters. A finite
watchdog prevents a hung test from running forever, but passing the watchdog alone
is not evidence that progress or cleanup occurred.

## Resource invariant

The decision preserves:

```text
resident resources = fixed node runtime + active activations + bounded shared caches and provider pools
```

A waiting activation is still an active activation. Dormant deployments acquire
no cell, Store, worker, listener, provider instance or descendant reservation.

## Consequences

- Asynchronous waiting improves runtime-thread utilization without weakening cell
  or budget ownership.
- Parent cells remain occupied during ordinary provider and child waits, so local
  descendant calls need an explicit fixed-capacity progress policy rather than
  relying on scheduler fairness alone.
- Cleanup and accounting remain conservative: uncertain retirement quarantines or
  retains ownership instead of producing an early refund.
- Fresh Store and activation-local binding guarantees remain unchanged across
  reuse.
- Durable suspension, continuation eviction, stack checkpointing, persistent
  warmed guest instances and per-service execution resources remain outside this
  decision.
