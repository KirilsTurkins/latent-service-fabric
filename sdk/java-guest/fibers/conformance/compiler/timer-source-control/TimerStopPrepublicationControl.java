import dev.latent.generated.Bindings;
import dev.latent.guest.Option;
import dev.latent.guest.runtime.Activation;
import java.lang.reflect.Field;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;

/** Private-ledger projection: pause close after its first gate, before count publication. */
public final class TimerStopPrepublicationControl {
    private static Field field(Class<?> type,String name) throws Exception {var f=type.getDeclaredField(name);f.setAccessible(true);return f;}
    private static Object get(String name) throws Exception {return field(Activation.class,name).get(null);}
    private static void set(String name,Object value) throws Exception {field(Activation.class,name).set(null,value);}
    private static void require(boolean value,String why){if(!value)throw new AssertionError(why);}
    private static void await(CountDownLatch latch){try{if(!latch.await(5,TimeUnit.SECONDS))throw new AssertionError("prepublication-timeout");}catch(InterruptedException e){throw new IllegalStateException(e);}}
    @SuppressWarnings("unchecked")
    public static void main(String[] args) throws Exception {
        var token=Bindings.LatentRuntimeActivation.register(Bindings.LatentRuntimeActivationOwnerKind.Task,Option.none()).value();
        var workClass=Class.forName("dev.latent.guest.runtime.Activation$Work");var ctor=workClass.getDeclaredConstructor(Bindings.LatentRuntimeActivationToken.class);ctor.setAccessible(true);var work=ctor.newInstance(token);
        ((Map<Thread,Object>)get("threads")).put(Thread.currentThread(),work);set("root",work);set("entered",true);
        var timer=Activation.timer(Activation.monotonicMillis()+1000);var original=field(Activation.Lease.class,"token").get(timer);
        var paused=new CountDownLatch(1);var release=new CountDownLatch(1);var error=new AtomicReference<Throwable>();
        Class.forName("dev.latent.guest.runtime.TeardownHooks").getField("beforeStopAction").set(null,(Runnable)() -> {paused.countDown();await(release);});
        Thread worker=new Thread(() -> {try{timer.close();}catch(Throwable failure){error.set(failure);}});worker.start();await(paused);
        Throwable completion=null;boolean retained;
        try {
            var finish=Activation.class.getDeclaredMethod("finishInvocation",boolean.class);finish.setAccessible(true);
            try {finish.invoke(null,true);}catch(java.lang.reflect.InvocationTargetException failure){completion=failure.getCause();}
            retained=((List<?>)get("timers")).contains(timer) && ((Map<?,?>)get("threads")).containsKey(Thread.currentThread())
                && field(workClass,"timer").get(work)==timer && field(Activation.Lease.class,"token").get(timer)==original;
        } finally {release.countDown();worker.join(5000);}
        require(!worker.isAlive(),"prepublication-worker-stuck");
        require(completion instanceof IllegalStateException && retained,"prepublication-teardown-lost-owner");
        require(error.get() instanceof IllegalStateException && Bindings.LatentRuntimeActivation.stops==0,
            "prepublication-started-host-stop");
        require((boolean)get("poisoned"),"prepublication-not-fenced");
        System.out.println("TIMER_STOP_PREPUBLICATION PASS retained;no-host-stop");
    }
}
