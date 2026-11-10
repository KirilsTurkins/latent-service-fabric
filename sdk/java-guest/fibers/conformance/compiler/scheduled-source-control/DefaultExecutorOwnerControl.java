import dev.latent.generated.Bindings.LatentRuntimeActivationOwnerKind;
import dev.latent.guest.runtime.Activation;
import dev.latent.guest.runtime.concurrent.CompletableFuture;
import java.lang.reflect.Field;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.Executor;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;

public final class DefaultExecutorOwnerControl {
    static void require(boolean ok,String message) { if (!ok) throw new AssertionError(message); }
    static void await(CountDownLatch latch,String message) throws InterruptedException {
        require(latch.await(5,TimeUnit.SECONDS),message);
    }
    static void join(Thread thread) throws InterruptedException {
        thread.join(5000); require(!thread.isAlive(),"thread-not-retired:"+thread.getName());
    }
    static void counts(int executors,int queued,int results) {
        require(Activation.count(LatentRuntimeActivationOwnerKind.Executor)==executors &&
                Activation.count(LatentRuntimeActivationOwnerKind.QueuedWork)==queued &&
                Activation.count(LatentRuntimeActivationOwnerKind.Result)==results,"owner-count");
    }
    static void retire(Executor facade) throws Exception {
        Field field=facade.getClass().getDeclaredField("pool"); field.setAccessible(true);
        ExecutorService pool=(ExecutorService)field.get(facade);
        require(pool!=null,"no-created-pool");
        pool.shutdown(); require(pool.awaitTermination(5,TimeUnit.SECONDS),"pool-not-retired");
        counts(0,0,0); Activation.idle();
    }
    static void failedInitialization(String mode) throws Exception {
        CompletableFuture<Integer> initial=new CompletableFuture<>();
        Executor facade=initial.defaultExecutor();
        CompletableFuture<Integer> failed=initial.thenApplyAsync(value -> value+1,facade);
        counts(0,1,1);
        if (mode.equals("denied")) Activation.denyNext="Executor";
        else {
            Activation.manageFailure=new IllegalStateException("injected-manage-failure");
            if (mode.equals("uncertain")) Activation.denyCloseNext="Executor";
        }
        require(initial.complete(41),"source-completion-refused");
        try { failed.get(5,TimeUnit.SECONDS); throw new AssertionError("failed-initialization-returned"); }
        catch (ExecutionException expected) {
            require(expected.getCause() instanceof IllegalStateException,"wrong-error-type");
        }
        if (mode.equals("uncertain")) {
            require(Activation.poisoned && Activation.failedLeaseAttempts()==1,"uncertain-not-fenced-once");
            counts(1,0,0);
            try { new CompletableFuture<Integer>().thenApplyAsync(value -> value+1,facade);
                  throw new AssertionError("poisoned-admission-accepted"); }
            catch (IllegalStateException expected) { }
            require(Activation.failedLeaseAttempts()==1,"uncertain-settlement-retried");
        } else {
            counts(0,0,0);
            Activation.manageFailure=null;
            try {
                CompletableFuture<Integer> retry=new CompletableFuture<>();
                CompletableFuture<Integer> result=retry.thenApplyAsync(value -> value+1,facade);
                require(retry.complete(41) && result.get(5,TimeUnit.SECONDS)==42,"fresh-retry-failed");
            } finally { retire(facade); }
        }
        System.out.println("DEFAULT_EXECUTOR_OWNER PASS "+mode);
    }
    static void concurrentInitialization() throws Exception {
        Executor facade=new CompletableFuture<Integer>().defaultExecutor();
        CountDownLatch go=new CountDownLatch(1), completed=new CountDownLatch(3);
        AtomicReference<Throwable> failure=new AtomicReference<>();
        Thread[] submitters=new Thread[3];
        for (int i=0;i<submitters.length;i++) {
            submitters[i]=new Thread(() -> {
                try { await(go,"start-gate"); facade.execute(completed::countDown); }
                catch (Throwable error) { failure.compareAndSet(null,error); }
            },"default-executor-submitter-"+i);
            submitters[i].start();
        }
        try {
            go.countDown(); await(completed,"callbacks-not-complete");
            for (Thread submitter:submitters) join(submitter);
            require(failure.get()==null,"submission-failed");
            require(Activation.admissions(LatentRuntimeActivationOwnerKind.Executor)==1,"duplicate-pool-admission");
            counts(1,0,0);
        } finally {
            go.countDown();
            try { for (Thread submitter:submitters) join(submitter); }
            finally { retire(facade); }
        }
        System.out.println("DEFAULT_EXECUTOR_OWNER PASS concurrent");
    }
    static void rejectionLock() throws Exception {
        CompletableFuture<Integer> source=new CompletableFuture<>();
        Executor facade=source.defaultExecutor();
        Object monitor;
        try {
            Field field=facade.getClass().getDeclaredField("lock"); field.setAccessible(true);
            monitor=field.get(facade);
        } catch (NoSuchFieldException oldSource) { monitor=facade; }
        Object selected=monitor;
        CountDownLatch acquired=new CountDownLatch(1);
        AtomicReference<Thread> contender=new AtomicReference<>();
        boolean[] freeDuringRetirement={false};
        CompletableFuture<Integer> failed=source.thenApplyAsync(value -> value+1,facade);
        Activation.denyNext="Executor";
        Activation.closeObservationKind="QueuedWork";
        Activation.closeObservation=() -> {
            Thread thread=new Thread(() -> { synchronized (selected) { acquired.countDown(); } },"facade-lock-contender");
            contender.set(thread); thread.start();
            try { freeDuringRetirement[0]=acquired.await(1,TimeUnit.SECONDS); }
            catch (InterruptedException error) { Thread.currentThread().interrupt(); }
        };
        require(source.complete(41),"source-completion-refused");
        try { failed.get(5,TimeUnit.SECONDS); throw new AssertionError("failed-initialization-returned"); }
        catch (ExecutionException expected) { require(expected.getCause() instanceof IllegalStateException,"wrong-error-type"); }
        require(contender.get()!=null,"retirement-observation-not-called");
        join(contender.get());
        counts(0,0,0); Activation.idle();
        require(freeDuringRetirement[0],"facade-lock-held-during-rejection");
        System.out.println("DEFAULT_EXECUTOR_OWNER PASS rejection-lock");
    }
    public static void main(String[] args) throws Exception {
        require(args.length==1,"mode-required");
        if (args[0].equals("concurrent")) concurrentInitialization();
        else if (args[0].equals("rejection-lock")) rejectionLock();
        else failedInitialization(args[0]);
    }
}
