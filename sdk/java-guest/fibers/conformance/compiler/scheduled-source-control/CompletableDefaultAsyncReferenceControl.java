import java.util.concurrent.CompletableFuture;
import java.util.concurrent.CompletionStage;
import java.util.concurrent.Executor;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.function.BiConsumer;
import java.util.function.Consumer;
import java.util.function.Supplier;

/** JDK and SDK source observations; no component or guest qualification. */
public final class CompletableDefaultAsyncReferenceControl {
    private static void require(boolean value) { if (!value) throw new AssertionError("default-async-reference"); }
    static final class Held implements Executor {
        Runnable action; int submissions; RuntimeException afterCapture;
        @Override public void execute(Runnable command) {
            require(action == null); action = command; submissions++;
            if (afterCapture != null) throw afterCapture;
        }
        void run() { Runnable selected = action; action = null; require(selected != null); selected.run(); }
    }
    static final class Overridden extends CompletableFuture<Integer> {
        final Held held = new Held();
        final RuntimeException explicit = new IllegalStateException("explicit-overload");
        RuntimeException defaultFailure;
        boolean nullDefault;
        int defaults, factories, overloads;
        @Override public Executor defaultExecutor() {
            defaults++;
            if (defaultFailure != null) throw defaultFailure;
            return nullDefault ? null : held;
        }
        @Override public <U> CompletableFuture<U> newIncompleteFuture() { factories++; return new CompletableFuture<>(); }
        @Override public CompletableFuture<Void> thenAcceptAsync(Consumer<? super Integer> fn, Executor executor) {
            overloads++; throw explicit;
        }
        @Override public CompletableFuture<Void> thenRunAsync(Runnable fn, Executor executor) {
            overloads++; throw explicit;
        }
        @Override public <U> CompletableFuture<Void> thenAcceptBothAsync(CompletionStage<? extends U> other,
                BiConsumer<? super Integer, ? super U> fn, Executor executor) {
            overloads++; throw explicit;
        }
        @Override public CompletableFuture<Void> runAfterBothAsync(CompletionStage<?> other, Runnable fn, Executor executor) {
            overloads++; throw explicit;
        }
        @Override public CompletableFuture<Void> acceptEitherAsync(CompletionStage<? extends Integer> other,
                Consumer<? super Integer> fn, Executor executor) {
            overloads++; throw explicit;
        }
        @Override public CompletableFuture<Integer> completeAsync(Supplier<? extends Integer> fn, Executor executor) {
            overloads++; throw explicit;
        }
    }
    private static void stage(String kind, boolean ready, boolean nullDefault) {
        var source = new Overridden(); var other = new CompletableFuture<Integer>();
        source.nullDefault = nullDefault;
        var calls = new AtomicInteger();
        if (ready) { source.complete(5); other.complete(7); }
        CompletableFuture<Void> child = switch (kind) {
            case "accept" -> source.thenAcceptAsync(value -> { require(value == 5); calls.incrementAndGet(); });
            case "run" -> source.thenRunAsync(calls::incrementAndGet);
            case "accept-both" -> source.thenAcceptBothAsync(other, (left, right) -> {
                require(left == 5 && right == 7); calls.incrementAndGet();
            });
            case "run-both" -> source.runAfterBothAsync(other, calls::incrementAndGet);
            case "accept-either" -> source.acceptEitherAsync(other, value -> { require(value == 5); calls.incrementAndGet(); });
            default -> throw new IllegalArgumentException(kind);
        };
        require(source.defaults == 1 && source.factories == 1 && source.overloads == 0);
        if (!ready) { require(!child.isDone() && source.held.submissions == 0 && calls.get() == 0); source.complete(5); other.complete(7); }
        if (!nullDefault) {
            require(source.held.submissions == 1 && !child.isDone() && calls.get() == 0);
            source.held.run();
        } else require(source.held.submissions == 0);
        require(child.isDone() && child.join() == null && calls.get() == 1);
    }
    private static void invalid(String kind, boolean nullOther, boolean throwDefault) {
        var source = new Overridden(); source.nullDefault = true;
        var other = new CompletableFuture<Integer>();
        if (throwDefault) source.defaultFailure = new IllegalStateException("default-failure");
        try {
            switch (kind) {
                case "accept" -> source.thenAcceptAsync(null);
                case "run" -> source.thenRunAsync(null);
                case "accept-both" -> {
                    if (nullOther) source.thenAcceptBothAsync((CompletionStage<Integer>)null, (left, right) -> {});
                    else source.thenAcceptBothAsync(other, null);
                }
                case "run-both" -> {
                    if (nullOther) source.runAfterBothAsync(null, () -> {});
                    else source.runAfterBothAsync(other, null);
                }
                case "accept-either" -> {
                    if (nullOther) source.acceptEitherAsync(null, value -> {});
                    else source.acceptEitherAsync(other, null);
                }
                default -> throw new IllegalArgumentException(kind);
            }
            throw new AssertionError("invalid-accepted");
        } catch (RuntimeException error) {
            require(throwDefault ? error == source.defaultFailure : error instanceof NullPointerException);
        }
        require(source.defaults == 1 && source.factories == 0 && source.overloads == 0 && source.held.submissions == 0);
    }
    private static void invalidBeforeOtherConversion(String kind, boolean invalidCallback) {
        var source = new Overridden(); source.nullDefault = true;
        class Other extends CompletableFuture<Integer> {
            final RuntimeException failure = new IllegalStateException("other-conversion");
            int conversions;
            @Override public CompletableFuture<Integer> toCompletableFuture() { conversions++; throw failure; }
        }
        var other = new Other();
        try {
            switch (kind) {
                case "accept-both" -> source.thenAcceptBothAsync(other, invalidCallback ? null : (left, right) -> {});
                case "run-both" -> source.runAfterBothAsync(other, invalidCallback ? null : () -> {});
                case "accept-either" -> source.acceptEitherAsync(other, invalidCallback ? null : value -> {});
                default -> throw new IllegalArgumentException(kind);
            }
            throw new AssertionError("invalid-accepted");
        } catch (RuntimeException error) {
            require(invalidCallback ? error instanceof NullPointerException : error == other.failure);
        }
        require(other.conversions == (invalidCallback ? 0 : 1));
        require(source.defaults == 1 && source.factories == 0 && source.overloads == 0 && source.held.submissions == 0);
    }
    private static void explicitCallsRemainVirtual() {
        var source = new Overridden();
        try { source.thenRunAsync(() -> {}, command -> {}); throw new AssertionError("explicit-overload-skipped"); }
        catch (IllegalStateException expected) { require(expected == source.explicit); }
        require(source.defaults == 0 && source.overloads == 1);
        try { source.completeAsync(() -> 1); throw new AssertionError("complete-async-overload-skipped"); }
        catch (IllegalStateException expected) { require(expected == source.explicit); }
        require(source.defaults == 1 && source.overloads == 2);
    }
    public static void main(String[] args) {
        for (String kind : new String[]{"accept", "run", "accept-both", "run-both", "accept-either"}) {
            stage(kind, false, false); stage(kind, true, false);
            stage(kind, false, true); stage(kind, true, true);
            invalid(kind, false, false); invalid(kind, false, true);
            if (kind.endsWith("both") || kind.equals("accept-either")) {
                invalid(kind, true, false); invalid(kind, true, true);
                invalidBeforeOtherConversion(kind, true); invalidBeforeOtherConversion(kind, false);
            }
        }
        explicitCallsRemainVirtual();
        System.out.println("COMPLETABLE_DEFAULT_ASYNC_REFERENCE PASS pending;ready;five-overloads;default-executor;null-default;invalid-order;factory;explicit-virtual");
    }
}
