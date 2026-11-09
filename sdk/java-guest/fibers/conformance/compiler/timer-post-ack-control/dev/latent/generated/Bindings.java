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
    public static Address dispatchBody(int operation, int inputAddress, int length) { throw new AssertionError("source-control-no-dispatch"); }
    public static Option<Reply<Unsigned64>> lsfRootTimerNext(LatentRuntimeActivationToken token) {
        return Option.some(LatentRuntimeActivation.timerNext(token));
    }
    public static Option<Reply<Void>> lsfRootWaitFor(Unsigned64 nanos, Option<LatentRuntimeActivationToken> continuation) {
        return Option.some(LatentRuntimeActivation.waitFor(nanos, continuation));
    }
    public static final class LatentRuntimeActivation {
        private static long next;
        private static final HashMap<LatentRuntimeActivationToken, LatentRuntimeActivationOwnerKind> owners = new HashMap<>();
        public static final ArrayList<LatentRuntimeActivationToken> selected = new ArrayList<>();
        public static int waits, stops, starts, registrations;
        public static boolean storeCancelled;
        public static final ArrayList<LatentRuntimeActivationToken> admittedTimers = new ArrayList<>();
        public static Runnable startObservation;
        public static long lastNanos;
        public static boolean denyNext, denyStop, denySettle, denyStart, nullStartToken;
        public static RuntimeException stopFailure;
        public static RuntimeException settleFailure;
        public static Runnable stopObservation, settleObservation;
        public static int timers() { return (int)owners.values().stream().filter(kind -> kind == LatentRuntimeActivationOwnerKind.Timer).count(); }
        public static Reply<LatentRuntimeActivationToken> register(LatentRuntimeActivationOwnerKind kind, Option<LatentRuntimeActivationToken> continuation) {
            registrations++;
            if (kind == LatentRuntimeActivationOwnerKind.Timer && timers() >= 2) return new Reply<>(null, Error.ResourceExhausted);
            var token = new LatentRuntimeActivationToken(1, ++next); owners.put(token, kind); return new Reply<>(token, null);
        }
        public static Reply<LatentRuntimeActivationToken> timerStart(Unsigned64 nanos, Option<Unsigned64> period, Option<LatentRuntimeActivationToken> continuation) {
            starts++; lastNanos = nanos.bits();
            if (denyStart) return new Reply<>(null, Error.ResourceExhausted);
            var accepted = register(LatentRuntimeActivationOwnerKind.Timer, continuation);
            if (!accepted.isError()) admittedTimers.add(accepted.value());
            Runnable observation = startObservation; startObservation = null;
            if (observation != null) observation.run();
            return nullStartToken && !accepted.isError() ? new Reply<>(null, null) : accepted;
        }
        // Synthetic Store cleanup for this private ledger only.
        public static boolean ownsTimer(LatentRuntimeActivationToken token) {
            return owners.get(token) == LatentRuntimeActivationOwnerKind.Timer;
        }
        public static void discardStore() { storeCancelled = true; owners.clear(); }
        public static Reply<Unsigned64> timerNext(LatentRuntimeActivationToken token) {
            if (denyNext) return new Reply<>(null, Error.Cancelled);
            if (owners.get(token) != LatentRuntimeActivationOwnerKind.Timer) return new Reply<>(null, Error.InvalidToken);
            selected.add(token); return new Reply<>(Unsigned64.ZERO, null);
        }
        public static Reply<Void> timerStop(LatentRuntimeActivationToken token) {
            stops++;
            if (stopObservation != null) stopObservation.run();
            if (denyStop) return new Reply<>(null, Error.Cancelled);
            var result = settle(token);
            if (stopFailure != null) throw stopFailure;
            return result;
        }
        public static Reply<Void> settle(LatentRuntimeActivationToken token) {
            Runnable observation = settleObservation; settleObservation = null;
            if (observation != null) observation.run();
            if (settleFailure != null) throw settleFailure;
            if (denySettle) return new Reply<>(null, Error.Cancelled);
            return new Reply<>(null, owners.remove(token) == null ? Error.InvalidToken : null);
        }
        public static Reply<Void> park(LatentRuntimeActivationToken token) { return new Reply<>(null, null); }
        public static Reply<Void> wake(LatentRuntimeActivationToken token) { return new Reply<>(null, null); }
        public static Reply<Void> close() { return new Reply<>(null, null); }
        public static Reply<Void> waitFor(Unsigned64 nanos, Option<LatentRuntimeActivationToken> continuation) {
            waits++; var owner = register(LatentRuntimeActivationOwnerKind.Timer, continuation);
            return owner.isError() ? new Reply<>(null, owner.error()) : settle(owner.value());
        }
    }
}
