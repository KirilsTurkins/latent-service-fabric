import java.util.concurrent.CancellationException;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.CompletionException;
import java.util.concurrent.CompletionStage;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;

/** Run unchanged against the JDK and with only the two SDK imports projected. */
public final class CompletableMinimalStageReferenceControl {
    private interface Checked { void run() throws Exception; }
    private static void require(boolean value, String message) { if (!value) throw new AssertionError(message); }
    private static void unsupported(Checked action) throws Exception {
        try { action.run(); throw new AssertionError("restricted-operation-succeeded"); }
        catch (UnsupportedOperationException expected) { }
    }
    private static void restricted(CompletableFuture<Integer> view) throws Exception {
        unsupported(() -> view.get());
        unsupported(() -> view.get(0, null));
        unsupported(() -> view.getNow(3));
        unsupported(() -> view.join());
        unsupported(() -> view.resultNow());
        unsupported(() -> view.exceptionNow());
        unsupported(() -> view.complete(3));
        unsupported(() -> view.completeExceptionally(null));
        unsupported(() -> view.cancel(false));
        unsupported(() -> view.obtrudeValue(3));
        unsupported(() -> view.obtrudeException(null));
        unsupported(() -> view.isDone());
        unsupported(() -> view.isCancelled());
        unsupported(() -> view.isCompletedExceptionally());
        unsupported(() -> view.state());
        unsupported(() -> view.getNumberOfDependents());
        unsupported(() -> view.completeAsync(null));
        unsupported(() -> view.completeAsync(null, null));
        unsupported(() -> view.newIncompleteFuture().isDone());
    }
    private static void copies() throws Exception {
        class Source extends CompletableFuture<Integer> {
            int factories, conversions;
            @Override public <U> CompletableFuture<U> newIncompleteFuture() { factories++; return new CompletableFuture<>(); }
            @Override public CompletableFuture<Integer> toCompletableFuture() { conversions++; return this; }
        }
        Source source = new Source();
        CompletionStage<Integer> view = source.minimalCompletionStage();
        require(source.factories == 0 && source.conversions == 0, "source-override-dispatched");
        CompletableFuture<Integer> first = view.toCompletableFuture();
        CompletableFuture<Integer> second = view.toCompletableFuture();
        require(first != second && first != source && (Object)first != view && !first.isDone() && !second.isDone(), "copy-identity");
        require(first.complete(99) && !source.isDone() && !second.isDone(), "copy-mutated-source");
        require(source.complete(7) && second.join() == 7, "pending-copy-result");
        source.obtrudeValue(11);
        require(view.toCompletableFuture().join() == 7 && first.join() == 99, "forced-source-changed-view");
        require(view.thenApply(value -> value + 35).toCompletableFuture().join() == 42, "view-composition");
        @SuppressWarnings("unchecked") var cast = (CompletableFuture<Integer>)view;
        restricted(cast);
        require(cast.copy().toCompletableFuture().join() == 7, "restricted-copy");
        require(cast.minimalCompletionStage().toCompletableFuture().join() == 7, "nested-minimal");
    }
    private static void failures() throws Exception {
        Throwable failure = new IllegalArgumentException("original");
        CompletionStage<Integer> failed = CompletableFuture.failedStage(failure);
        AtomicReference<Throwable> direct = new AtomicReference<>();
        failed.handle((value, error) -> { direct.set(error); return null; }).toCompletableFuture().join();
        require(direct.get() == failure, "failed-stage-error-identity");
        try { failed.toCompletableFuture().join(); throw new AssertionError("failed-stage-returned"); }
        catch (CompletionException expected) { require(expected.getCause() == failure, "failed-stage-cause"); }
        try { CompletableFuture.failedStage(null); throw new AssertionError("null-failure-accepted"); }
        catch (NullPointerException expected) { }
        CompletableFuture<Integer> source = new CompletableFuture<>();
        CompletionStage<Integer> view = source.minimalCompletionStage();
        AtomicReference<Throwable> observed = new AtomicReference<>();
        view.handle((value, error) -> { observed.set(error); return null; });
        source.completeExceptionally(failure);
        require(observed.get() instanceof CompletionException && observed.get().getCause() == failure, "relayed-failure");
        CompletableFuture<Integer> cancelled = new CompletableFuture<>();
        CompletionStage<Integer> cancelledView = cancelled.minimalCompletionStage();
        require(cancelled.cancel(false), "source-cancel");
        CompletableFuture<Integer> copy = cancelledView.toCompletableFuture();
        require(!copy.isCancelled() && copy.isCompletedExceptionally(), "cancelled-copy-state");
        try { copy.join(); throw new AssertionError("cancelled-copy-returned"); }
        catch (CompletionException expected) { require(expected.getCause() instanceof CancellationException, "cancelled-copy-cause"); }
    }
    public static void main(String[] args) throws Exception {
        CompletionStage<Integer> ready = CompletableFuture.completedStage(42);
        require(ready.toCompletableFuture().join() == 42, "completed-stage");
        @SuppressWarnings("unchecked") var cast = (CompletableFuture<Integer>)ready;
        restricted(cast); copies(); failures();
        System.out.println("COMPLETABLE_MINIMAL_STAGE PASS restriction;factories;copies;composition;failure;cancel");
    }
}
