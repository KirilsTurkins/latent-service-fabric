import dev.latent.generated.Bindings;
import dev.latent.guest.Option;
import dev.latent.guest.runtime.Activation;
import java.lang.reflect.Field;
import java.util.Map;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;

/** Private-ledger projection of an admission resuming after teardown. */
public final class TimerAdmissionRaceControl {
    private static Field field(Class<?> t,String n) throws Exception {var f=t.getDeclaredField(n);f.setAccessible(true);return f;}
    private static Object get(String n)throws Exception{return field(Activation.class,n).get(null);}
    private static void set(String n,Object v)throws Exception{field(Activation.class,n).set(null,v);}
    private static void require(boolean ok,String why){if(!ok)throw new AssertionError(why);}
    private static void await(CountDownLatch l){try{if(!l.await(5,TimeUnit.SECONDS))throw new AssertionError("admission-timeout");}catch(InterruptedException e){throw new IllegalStateException(e);}}
    @SuppressWarnings("unchecked")
    public static void main(String[] args)throws Exception{
        var workClass=Class.forName("dev.latent.guest.runtime.Activation$Work");var ctor=workClass.getDeclaredConstructor(Bindings.LatentRuntimeActivationToken.class);ctor.setAccessible(true);
        var rootToken=Bindings.LatentRuntimeActivation.register(Bindings.LatentRuntimeActivationOwnerKind.Task,Option.none()).value();var root=ctor.newInstance(rootToken);
        var threads=(Map<Thread,Object>)get("threads");threads.put(Thread.currentThread(),root);set("root",root);set("entered",true);
        var paused=new CountDownLatch(1);var release=new CountDownLatch(1);var error=new AtomicReference<Throwable>();var value=new AtomicReference<Activation.Lease>();
        Class.forName("dev.latent.guest.runtime.TeardownHooks").getField("beforeAdmissionAction").set(null,(Runnable)() -> {paused.countDown();await(release);});
        Thread worker=new Thread(() -> {try{value.set(Activation.timer(Activation.monotonicMillis()+1000));}catch(Throwable failure){error.set(failure);}});
        var workerToken=Bindings.LatentRuntimeActivation.register(Bindings.LatentRuntimeActivationOwnerKind.Task,Option.none()).value();var workerWork=ctor.newInstance(workerToken);threads.put(worker,workerWork);
        worker.start();await(paused);boolean exceptional=args[0].equals("exceptional");Throwable marker=new IllegalStateException("original-failure");Throwable observed=null;
        try {
            var finish=Activation.class.getDeclaredMethod("finishInvocation",boolean.class);finish.setAccessible(true);
            if(exceptional){try{throw marker;}finally{finish.invoke(null,false);}}
            else finish.invoke(null,true);
        }catch(Throwable failure){observed=failure;}finally{release.countDown();worker.join(5000);}
        require(!worker.isAlive(),"admission-worker-stuck");
        if(exceptional)require(observed==marker && (boolean)get("poisoned") && threads.get(worker)==workerWork,"exceptional-admission-owner-not-retained");
        else require(observed==null,"clean-mode-unexpected-failure");
        require(error.get() instanceof IllegalStateException && value.get()==null && Bindings.LatentRuntimeActivation.timers()==0,
            "timer-admitted-after-teardown");
        System.out.println("TIMER_ADMISSION_RACE PASS "+args[0]);
    }
}
