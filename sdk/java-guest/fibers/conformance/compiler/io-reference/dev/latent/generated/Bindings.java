package dev.latent.generated;

import dev.latent.guest.Option;
import dev.latent.guest.Result;
import dev.latent.guest.Unit;
import dev.latent.guest.Unsigned64;

/** Private reference-process interpretation; never a component input. */
public final class Bindings {
    public static final class LatentRuntimeActivation {
        public static Result<Unit, String> waitFor(Unsigned64 nanos, Option<?> continuation) {
            if (continuation.isSome() || nanos.bits() < 0 || nanos.bits() > 1_000_000_000L)
                throw new AssertionError("bounded-reference-wait-only");
            try { Thread.sleep(nanos.bits() / 1_000_000, (int)(nanos.bits() % 1_000_000)); }
            catch (InterruptedException error) { throw new IllegalStateException(error); }
            return Result.ok(Unit.VALUE);
        }
    }
}
