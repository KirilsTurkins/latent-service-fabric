# FutureTask cancellation after an interrupt failure

This is a focused implementation and host/source regression control for #741,
not complete Java runtime qualification.

`FutureTask.cancel(true)` publishes the cancelled state before interrupting the
physical runner. A custom `Thread.interrupt()` can throw before or after delivery.
That failure must not skip notification of already-blocked getters or the
accepted cancellation's `done()` hook. The hook runs once, outside the future's
monitor. When both interrupt and `done()` throw, the completion-hook exception
escapes, matching the tested reference-JDK behavior.

The implementation runs cancellation cleanup in a `finally` block and calls
`done()` from an outer `finally`, after releasing the future monitor. It leaves a
running task's Result lease with its physical runner until that runner returns.
It does not retry a refused or uncertain Result settlement, and preserves the
existing fence and suppression of application completion hooks in that case.
No instance fields, explicit allocation sites, capability grants, runtime imports
or heap limits are added. Compiled continuation layout and physical guest memory
cost have not been measured.

## Host/source control

Run from the repository root with a fresh output directory. The two files under
`scheduled-source-control/dev` are the existing test-only ledger and vocabulary;
they must never be compiled into a guest component.

```sh
OUT="$(mktemp -d)"
CONTROL=sdk/java-guest/fibers/conformance/compiler/scheduled-source-control
javac -d "$OUT" \
  sdk/java-guest/fibers/dev/latent/guest/runtime/concurrent/FutureTask.java \
  "$CONTROL/dev/latent/generated/Bindings.java" \
  "$CONTROL/dev/latent/guest/runtime/Activation.java" \
  "$CONTROL/FutureTaskInterruptFailureControl.java"
CLASS=dev.latent.guest.runtime.concurrent.FutureTaskInterruptFailureControl
for implementation in source jdk; do
  for mode in before-runtime after-runtime before-error after-error \
      before-runtime-done-error after-error-done-error normal no-interrupt \
      pending completed failed; do
    java -cp "$OUT" "$CLASS" "$implementation" "$mode" || exit 1
  done
done
for mode in refused lost-ack; do
  java -cp "$OUT" "$CLASS" source "$mode" || exit 1
done
rm -rf "$OUT"
```

Each mode runs in a fresh JVM. Actual getter `WAITING` state establishes that
`get()` has blocked; latch signaling controls callable entry and physical exit.
There is no sleep or fixed yield-count readiness assumption. The control retains
an active runner until after cancellation observations and then requires its
`finally` block and physical thread retirement. A separate bounded cleanup
interval prevents failed assertions from retaining test threads.

The shared matrix covers failures before and after interrupt delivery,
RuntimeException and Error propagation, a throwing `done()` hook, ordinary
interrupting and non-interrupting cancellation, cancellation before execution,
already successful and failed futures, duplicate cancellation, and blocked
getters. Source-only controls cover refused settlement and lost acknowledgement.
The ledger verifies that the physical runner retains the original Result owner
and that successful retirement settles it once.

## Evidence boundary

The local comparison used OpenJDK 21.0.12.1 and the exact development runtime
blob `1c1d16357056e6d995cccb749b24643c9f654305` from revision
`b8b53a03cd808b9e8e6c0741f0494dcf0e38e4c8`. A fresh comparison against development
`64b81e819e36f95d0f1280e728562fa49b842dee` verified the same runtime and private
ledger inputs and reran all 24 cases. The unmodified source failed the six
exceptional-interrupt cases; the corrected source and reference controls passed.
This is not the repository's pinned JDK 25 run, the TeaVM compiler/model check,
a signed/admitted component run, or a physical guest memory measurement.

The control is explicitly runnable but has not been wired into the existing
hosted qualification owner in this patch. Full owner/contract integration and
signed regression execution remain required before treating this change as
qualified. The issue's checkpoint, aggregate-accounting, networking and full
qualification requirements remain open.
