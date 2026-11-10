import java.util.concurrent.CompletableFuture;
import java.util.concurrent.Executor;

/** The SDK source-port copy replaces only the import above. */
public final class CompletableOverrideReadinessReferenceControl {
    private static boolean sourcePort;
    private static final class Misleading<T> extends CompletableFuture<T> {
        final boolean answer;
        int calls;
        Misleading(boolean answer) { this.answer = answer; }
        @Override public boolean isDone() { calls++; return answer; }
        // This is unrelated to the SDK's private helper, and must not be called.
        public boolean completionRecorded() { throw new AssertionError("private-helper-dispatched"); }
    }
    private static final class Throwing<T> extends CompletableFuture<T> {
        @Override public boolean isDone() { throw new AssertionError("user-observer-internal-dispatch"); }
    }
    private static final class Maker<T> extends CompletableFuture<T> {
        final boolean childAnswer;
        int factories;
        Maker(boolean childAnswer) { this.childAnswer = childAnswer; }
        @Override public <U> CompletableFuture<U> newIncompleteFuture() {
            factories++;
            return new Misleading<U>(childAnswer);
        }
    }
    private static final class Held implements Executor {
        Runnable action;
        int submissions;
        @Override public void execute(Runnable next) {
            require(action == null, "multiple-submissions");
            action = next; submissions++;
        }
        void run() { if (action != null) { Runnable selected = action; action = null; selected.run(); } }
    }
    private static void require(boolean value, String message) { if (!value) throw new AssertionError(message); }
    private static void owners(int queued, int results) {
        if (!sourcePort) return;
        try {
            Class<?> ledger = Class.forName("dev.latent.guest.runtime.Activation");
            require((Integer)ledger.getMethod("queuedOwners").invoke(null) == queued
                && (Integer)ledger.getMethod("resultOwners").invoke(null) == results, "original-source-ledger");
        } catch (ReflectiveOperationException error) { throw new AssertionError(error); }
    }
    private static boolean failedWith(CompletableFuture<?> future, Class<?> type) {
        try { future.getNow(null); return false; }
        catch (RuntimeException error) { return type.isInstance(error.getCause()); }
    }
    private static void unary(boolean answer) {
        Misleading<Integer> source = new Misleading<>(answer);
        CompletableFuture<Integer> child = source.thenApply(v -> v + 1);
        owners(1, 1);
        require(child.getNow(null) == null, "unary-premature");
        source.complete(41);
        require(child.getNow(null) == 42 && source.calls == 0, "unary-result");
        owners(0, 0);
        require(source.isDone() == answer && source.calls == 1, "public-observer-dispatch");
    }
    private static void aggregate(boolean answer) {
        Misleading<String> source = new Misleading<>(answer);
        CompletableFuture<Void> all = CompletableFuture.allOf(source);
        CompletableFuture<Object> any = CompletableFuture.anyOf(source);
        owners(2, 2);
        require(!all.isDone() && any.getNow(null) == null, "aggregate-premature");
        source.complete("ok");
        require(all.isDone() && "ok".equals(any.getNow(null)) && source.calls == 0, "aggregate-result");
        owners(0, 0);
    }
    private static void binary(boolean answer) {
        Misleading<Integer> left = new Misleading<>(answer);
        CompletableFuture<Integer> right = new CompletableFuture<>();
        CompletableFuture<Integer> child = left.thenCombine(right, Integer::sum);
        right.complete(1);
        owners(1, 1);
        require(child.getNow(null) == null, "binary-premature");
        left.complete(41);
        require(child.getNow(null) == 42 && left.calls == 0, "binary-result");
        owners(0, 0);
    }
    private static void either(boolean answer) {
        Misleading<Integer> left = new Misleading<>(answer);
        CompletableFuture<Integer> right = new CompletableFuture<>();
        CompletableFuture<Integer> child = left.applyToEither(right, v -> v + 1);
        owners(1, 1);
        require(child.getNow(null) == null, "either-premature");
        left.complete(41); right.complete(1);
        require(child.getNow(null) == 42 && left.calls == 0, "either-selection");
        owners(0, 0);
    }
    private static void binaryRight(boolean answer) {
        CompletableFuture<Integer> left = new CompletableFuture<>();
        Misleading<Integer> right = new Misleading<>(answer);
        CompletableFuture<Integer> child = left.thenCombine(right, Integer::sum);
        left.complete(1);
        owners(1, 1);
        require(child.getNow(null) == null, "binary-right-premature");
        right.complete(41);
        require(child.getNow(null) == 42 && right.calls == 0, "binary-right-result");
        owners(0, 0);
    }
    private static void eitherRight(boolean answer) {
        CompletableFuture<Integer> left = new CompletableFuture<>();
        Misleading<Integer> right = new Misleading<>(answer);
        CompletableFuture<Integer> child = left.applyToEither(right, v -> v + 1);
        owners(1, 1);
        require(child.getNow(null) == null, "either-right-premature");
        right.complete(41);
        require(child.getNow(null) == 42 && right.calls == 0, "either-right-selection");
        left.complete(1);
        owners(0, 0);
    }
    private static void eitherAny(boolean answer) {
        Misleading<Integer> left = new Misleading<>(answer);
        CompletableFuture<Integer> right = new CompletableFuture<>();
        int[] calls = {0};
        CompletableFuture<Void> child = left.runAfterEither(right, () -> calls[0]++);
        owners(1, 1);
        require(!child.isDone() && calls[0] == 0, "either-any-premature");
        left.complete(41);
        require(child.isDone() && calls[0] == 1 && left.calls == 0, "either-any-selection");
        right.complete(1);
        owners(0, 0);
    }
    private static void readyBinaryFailure() {
        Misleading<Integer> left = new Misleading<>(false);
        left.completeExceptionally(new IllegalArgumentException("original"));
        Held executor = new Held();
        CompletableFuture<Integer> child = left.thenCombineAsync(CompletableFuture.completedFuture(1), Integer::sum, executor);
        require(executor.submissions == 1 && child.getNow(null) == null, "binary-shortcut-dispatch");
        owners(1, 1);
        executor.run();
        require(failedWith(child, IllegalArgumentException.class) && left.calls == 0, "binary-shortcut-failure");
        owners(0, 0);
    }
    private static void readyBinaryFailureRight() {
        CompletableFuture<Integer> left = new CompletableFuture<>();
        left.completeExceptionally(new IllegalArgumentException("original"));
        Misleading<Integer> right = new Misleading<>(false);
        right.complete(1);
        Held executor = new Held();
        CompletableFuture<Integer> child = left.thenCombineAsync(right, Integer::sum, executor);
        require(executor.submissions == 1 && child.getNow(null) == null, "binary-right-shortcut-dispatch");
        owners(1, 1);
        executor.run();
        require(failedWith(child, IllegalArgumentException.class) && right.calls == 0, "binary-right-shortcut-failure");
        owners(0, 0);
    }
    private static void destination(boolean answer, boolean completeFirst) {
        Maker<Integer> source = new Maker<>(answer);
        Held executor = new Held();
        int[] callbacks = {0};
        CompletableFuture<Integer> child = source.thenApplyAsync(v -> { callbacks[0]++; return v + 1; }, executor);
        require(source.factories == 1, "overridden-factory-not-used");
        source.complete(41);
        if (completeFirst) child.complete(99);
        owners(1, 1);
        executor.run();
        require(child.getNow(null) == (completeFirst ? 99 : 42)
            && callbacks[0] == (completeFirst ? 0 : 1), "destination-readiness");
        owners(0, 0);
    }
    private static void throwingObserver() {
        Throwing<Integer> source = new Throwing<>();
        CompletableFuture<Integer> child = source.thenApply(v -> v + 1);
        owners(1, 1);
        source.complete(41);
        require(child.getNow(null) == 42, "throwing-observer");
        owners(0, 0);
    }
    public static void main(String[] args) throws Exception {
        sourcePort = args.length == 1 && args[0].equals("source");
        unary(false); unary(true); aggregate(false); aggregate(true);
        binary(false); binary(true); either(false); either(true);
        binaryRight(false); binaryRight(true); eitherRight(false); eitherRight(true);
        eitherAny(false); eitherAny(true); readyBinaryFailure(); readyBinaryFailureRight();
        destination(true, false); destination(false, true); throwingObserver();
        if (sourcePort) {
            Class<?> ledger = Class.forName("dev.latent.guest.runtime.Activation");
            require((Integer)ledger.getMethod("owners").invoke(null) == 0, "unretired-source-ledger");
            ledger.getMethod("cleanup").invoke(null);
        }
        System.out.println("COMPLETABLE_OVERRIDE_READINESS_REFERENCE PASS cases=19;public-dispatch;private-helper");
    }
}
