import dev.latent.generated.Bindings;
import dev.latent.guest.Option;
import dev.latent.guest.runtime.Activation;
import java.lang.reflect.Field;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;

/** Private-ledger source projection of a stop starting immediately after teardown's sample. */
public final class TimerTeardownRaceControl {
    private static Field field(Class<?> type,String name) throws Exception { var f=type.getDeclaredField(name);f.setAccessible(true);return f; }
    private static Object get(String name) throws Exception {return field(Activation.class,name).get(null);}
    private static void set(String name,Object value) throws Exception {field(Activation.class,name).set(null,value);}
    private static void require(boolean value,String message) {if(!value) throw new AssertionError(message);}
    private static void await(CountDownLatch latch) {
        try {if(!latch.await(5,TimeUnit.SECONDS))throw new AssertionError("teardown-control-timeout");}
        catch(InterruptedException error){throw new IllegalStateException(error);}
    }
    private static void hook(Runnable action) throws Exception {Class.forName("dev.latent.guest.runtime.TeardownHooks").getField("action").set(null,action);}
    private static void finish(boolean returning) throws Exception {
        var method=Activation.class.getDeclaredMethod("finishInvocation",boolean.class);method.setAccessible(true);
        try {method.invoke(null,returning);}
        catch(java.lang.reflect.InvocationTargetException error){
            if(error.getCause() instanceof Exception exception)throw exception;
            if(error.getCause() instanceof Error exception)throw exception;
            throw error;
        }
    }
    @SuppressWarnings("unchecked")
    public static void main(String[] args) throws Exception {
        var token=Bindings.LatentRuntimeActivation.register(Bindings.LatentRuntimeActivationOwnerKind.Task,Option.none()).value();
        var workClass=Class.forName("dev.latent.guest.runtime.Activation$Work");
        var constructor=workClass.getDeclaredConstructor(Bindings.LatentRuntimeActivationToken.class);constructor.setAccessible(true);
        var work=constructor.newInstance(token);
        ((Map<Thread,Object>)get("threads")).put(Thread.currentThread(),work);
        set("root",work);set("entered",true);
        switch(args[0]) {
            case "race" -> {
                var timer=Activation.timer(Activation.monotonicMillis()+1000);
                var timerToken=field(Activation.Lease.class,"token").get(timer);
                var entered=new CountDownLatch(1);var release=new CountDownLatch(1);
                var worker=new AtomicReference<Thread>();var error=new AtomicReference<Throwable>();
                Bindings.LatentRuntimeActivation.stopObservation=() -> {entered.countDown();await(release);};
                hook(() -> {
                    Thread thread=new Thread(() -> {
                        try {timer.close();} catch(Throwable failure) {error.set(failure);entered.countDown();}
                    });
                    worker.set(thread);thread.start();await(entered);
                });
                Throwable completion=null;boolean retained;boolean tokenRetained;int stops;
                try {finish(true);} catch(Throwable failure) {completion=failure;}
                finally {
                    retained=((List<?>)get("timers")).contains(timer) && ((Map<?,?>)get("threads")).containsKey(Thread.currentThread())
                        && field(workClass,"timer").get(work)==timer;
                    tokenRetained=field(Activation.Lease.class,"token").get(timer)==timerToken;
                    stops=Bindings.LatentRuntimeActivation.stops;
                    release.countDown();if(worker.get()!=null)worker.get().join(5000);
                }
                require(worker.get()!=null && !worker.get().isAlive(),"teardown-stop-worker-stuck");
                require(completion instanceof IllegalStateException,"teardown-return-not-refused");
                require(retained && tokenRetained,"teardown-cleared-live-timer-owner");
                require(stops==0 && error.get() instanceof IllegalStateException,"teardown-allowed-new-stop");
                require((boolean)get("poisoned"),"teardown-not-poisoned");
            }
            case "exceptional" -> {
                var timer=Activation.timer(Activation.monotonicMillis()+1000);
                var marker=new IllegalStateException("original-invocation-failure");Throwable observed=null;
                try {try {throw marker;} finally {finish(false);}} catch(Throwable failure){observed=failure;}
                require(observed==marker,"teardown-masked-primary-exception");
                require((boolean)get("poisoned") && ((List<?>)get("timers")).contains(timer)
                    && ((Map<?,?>)get("threads")).containsKey(Thread.currentThread()) && field(workClass,"timer").get(work)==timer,
                    "exceptional-teardown-cleared-live-timer");
            }
            case "clean" -> {
                finish(true);
                require(!(boolean)get("poisoned") && !(boolean)get("entered") && get("root")==null
                    && ((Map<?,?>)get("threads")).isEmpty(),"clean-teardown-changed");
            }
            case "closed-before" -> {
                var timer=Activation.timer(Activation.monotonicMillis()+1000);timer.close();finish(true);
                require(!(boolean)get("poisoned") && !(boolean)get("entered") && get("root")==null
                    && Bindings.LatentRuntimeActivation.stops==1,"confirmed-stop-teardown-changed");
            }
            default -> throw new IllegalArgumentException("unknown mode");
        }
        System.out.println("TIMER_TEARDOWN_CONTROL PASS "+args[0]);
    }
}
