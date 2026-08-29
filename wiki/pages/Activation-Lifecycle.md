<!-- LSF-WIKI-MANAGED -->
# Activation lifecycle

An activation is the temporary ownership boundary for one invocation. Phase 0
implements the following local lifecycle through `Phase0ActivationRunner` and
the Wasmtime backend.

## Lifecycle

1. Register bounded cancellation state and derive the effective deadline.
2. Acquire a generic cell from the fixed pool, observing cancellation and
   deadline while queued.
3. Recheck cancellation/deadline after accepting the affine lease.
4. Build a fresh execution request and invoke the prepared component.
5. Drop the guest instance, store, host state, temporary buffers, and
   cancellation probe.
6. Publish bounded logs and an explicit cleanup proof.
7. Release the cell only when cleanup is reusable; otherwise quarantine it.
8. Remove the cancellation registration and report the terminal outcome.

## Precedence and containment

The Phase 0 runner makes outcome races deterministic:

```text
cancellation > deadline > memory exhaustion > fuel exhaustion > guest trap > generic runtime failure
```

Cancellation and deadline are checked before a cell grant, again after grant,
and at guest-result handoff. A failed cell disposition overrides the guest
outcome because safe ownership can no longer be asserted.

## Outcomes

The echo fixture demonstrates successful output and a declared domain error.
Infrastructure failures remain separate platform errors. Phase 0 also covers
trap, timeout, explicit cancellation, fuel/memory exhaustion, and recovery
with a healthy invocation after each required failure class.

Every activation receives a fresh store and host state. No store, instance,
input buffer, host context, cancellation probe, or unbounded log history may
cross into the next activation.

## What is still future work

Phase 0 is not the retained activation-status API, generic invocation API,
route-pinned lifecycle, state/effect commit lifecycle, or remote activation
model. Those concepts belong to later Phase 1+ contract and runtime work.

See the authoritative [activation containment specification](https://github.com/KirilsTurkins/latent-service-fabric/blob/development/docs/development/activation-containment.md)
and [activation protocol](https://github.com/KirilsTurkins/latent-service-fabric/blob/development/docs/protocol/activation-lifecycle.md).
