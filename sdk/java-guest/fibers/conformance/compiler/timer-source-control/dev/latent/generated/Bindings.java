package dev.latent.generated;

import dev.latent.guest.Option;
import dev.latent.guest.Unsigned64;
import java.util.HashMap;
import java.util.ArrayList;
import org.teavm.interop.Address;

/** Private source-control ledger; excluded from every component recipe. */
public final class Bindings {
    public enum LatentRuntimeActivationOwnerKind { Task, ManagedIdleWorker, Executor, QueuedWork, Wait, Timer, Result, Native }
    public enum Error { ResourceExhausted, Cancelled, InvalidToken }
    public record LatentRuntimeActivationToken(long generation, long id) { }
    public record Reply<T>(T value, Error error) { public boolean isError() { return error != null; } }
    public static Address dispatchBody(int operation, Address data, int length) { throw new AssertionError("source-control-no-dispatch"); }
    public static final class LatentRuntimeActivation {
        private static long next;
        private static final HashMap<LatentRuntimeActivationToken, LatentRuntimeActivationOwnerKind> owners = new HashMap<>();
        public static final ArrayList<LatentRuntimeActivationToken> selected = new ArrayList<>();
        public static int waits, stops;
        public static long lastNanos;
        public static boolean denyNext, denyStop;
        public static Runnable stopObservation;
        public static int timers() { return (int)owners.values().stream().filter(kind -> kind == LatentRuntimeActivationOwnerKind.Timer).count(); }
        public static Reply<LatentRuntimeActivationToken> register(LatentRuntimeActivationOwnerKind kind, Option<LatentRuntimeActivationToken> continuation) {
            if (kind == LatentRuntimeActivationOwnerKind.Timer && timers() >= 2) return new Reply<>(null, Error.ResourceExhausted);
            var token = new LatentRuntimeActivationToken(1, ++next); owners.put(token, kind); return new Reply<>(token, null);
        }
        public static Reply<LatentRuntimeActivationToken> timerStart(Unsigned64 nanos, Option<Unsigned64> period, Option<LatentRuntimeActivationToken> continuation) {
            lastNanos = nanos.bits(); return register(LatentRuntimeActivationOwnerKind.Timer, continuation);
        }
        public static Reply<Unsigned64> timerNext(LatentRuntimeActivationToken token) {
            if (denyNext) return new Reply<>(null, Error.Cancelled);
            if (owners.get(token) != LatentRuntimeActivationOwnerKind.Timer) return new Reply<>(null, Error.InvalidToken);
            selected.add(token); return new Reply<>(Unsigned64.ZERO, null);
        }
        public static Reply<Void> timerStop(LatentRuntimeActivationToken token) {
            stops++;
            if (stopObservation != null) stopObservation.run();
            if (denyStop) return new Reply<>(null, Error.Cancelled);
            return settle(token);
        }
        public static Reply<Void> settle(LatentRuntimeActivationToken token) { return new Reply<>(null, owners.remove(token) == null ? Error.InvalidToken : null); }
        public static Reply<Void> park(LatentRuntimeActivationToken token) { return new Reply<>(null, null); }
        public static Reply<Void> wake(LatentRuntimeActivationToken token) { return new Reply<>(null, null); }
        public static Reply<Void> close() { return new Reply<>(null, null); }
        public static Reply<Void> waitFor(Unsigned64 nanos, Option<LatentRuntimeActivationToken> continuation) {
            waits++; var owner = register(LatentRuntimeActivationOwnerKind.Timer, continuation);
            return owner.isError() ? new Reply<>(null, owner.error()) : settle(owner.value());
        }
    }
}
