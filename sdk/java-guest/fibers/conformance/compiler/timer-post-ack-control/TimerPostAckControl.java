import dev.latent.generated.Bindings;
import dev.latent.guest.Option;
import dev.latent.guest.runtime.Activation;
import dev.latent.guest.runtime.PostAckHooks;
import java.lang.reflect.Field;
import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicReference;

/** Test-only post-acknowledgement owner/rollback projection, not a guest witness. */
public final class TimerPostAckControl {
    private static Field field(Class<?> type,String name)throws Exception{var f=type.getDeclaredField(name);f.setAccessible(true);return f;}
    private static Object get(String name)throws Exception{return field(Activation.class,name).get(null);}
    private static void set(String name,Object value)throws Exception{field(Activation.class,name).set(null,value);}
    private static void need(boolean condition,String why){if(!condition)throw new AssertionError(why);}
    private static Object token(Object timer)throws Exception{return field(Activation.Lease.class,"token").get(timer);}
    private static void finish()throws Exception{
        var method=Activation.class.getDeclaredMethod("finishInvocation",boolean.class);method.setAccessible(true);
        try{method.invoke(null,true);}catch(java.lang.reflect.InvocationTargetException e){if(e.getCause() instanceof Exception x)throw x;if(e.getCause() instanceof Error x)throw x;throw e;}
    }
    @SuppressWarnings("unchecked")
    public static void main(String[]args)throws Exception{
        var rootToken=Bindings.LatentRuntimeActivation.register(Bindings.LatentRuntimeActivationOwnerKind.Task,Option.none()).value();
        var workClass=Class.forName("dev.latent.guest.runtime.Activation$Work");
        var ctor=workClass.getDeclaredConstructor(Bindings.LatentRuntimeActivationToken.class);ctor.setAccessible(true);Object work=ctor.newInstance(rootToken);
        var threadMap=(Map<Thread,Object>)get("threads");threadMap.put(Thread.currentThread(),work);set("root",work);set("entered",true);
        var timerField=field(workClass,"timer");var timers=(List<?>)get("timers");var failures=(AtomicReference<Activation.Lease>)get("failedQueuedOwners");
        var original=new IllegalStateException("original-registration-failure");
        switch(args[0]){
            case "normal" -> {
                long deadline=Activation.monotonicMillis()+1000;var lease=Activation.timer(deadline);
                need(timerField.get(work)==lease && timers.contains(lease) && !(boolean)get("poisoned"),"normal-registration");
                Activation.beginTimedFrame(lease);need(Activation.timerDeadline(-1)==deadline,"normal-deadline");Activation.endTimedFrame(lease);
                lease.close();need(timers.isEmpty() && Bindings.LatentRuntimeActivation.timers()==0 && Bindings.LatentRuntimeActivation.stops==1,"normal-stop");finish();
            }
            case "refused-start" -> {
                Bindings.LatentRuntimeActivation.denyStart=true;
                try{Activation.timer(Activation.monotonicMillis()+1000);throw new AssertionError("expected-refusal");}
                catch(IllegalStateException error){need(error.getMessage().equals("activation-runtime-timer-start-ResourceExhausted"),"refusal-shape");}
                need(failures.get()==null && !(boolean)get("poisoned") && timers.isEmpty() && Bindings.LatentRuntimeActivation.stops==0,"refusal-not-poisoned");finish();
            }
            case "rollback-confirmed", "rollback-refused", "rollback-lost", "after-list" -> {
                PostAckHooks.failure=original;PostAckHooks.afterList=args[0].equals("after-list");
                Bindings.LatentRuntimeActivation.denyStop=args[0].equals("rollback-refused");
                if(args[0].equals("rollback-lost"))Bindings.LatentRuntimeActivation.stopFailure=new IllegalStateException("lost-stop-ack");
                try{Activation.timer(Activation.monotonicMillis()+1000);throw new AssertionError("expected-failure");}
                catch(IllegalStateException error){need(error==original,"original-error-must-stay-primary");}
                var holder=failures.get();boolean known=args[0].equals("rollback-refused")||args[0].equals("rollback-lost");
                need(holder!=null && (token(holder)!=null)==known && (boolean)get("poisoned") && Bindings.LatentRuntimeActivation.stops==1,"holder-and-stop-state");
                need(Bindings.LatentRuntimeActivation.timers()==(args[0].equals("rollback-refused")?1:0),"host-model-owner");
                need(timers.contains(holder)==args[0].equals("after-list"),"partial-registry-state");
                try{finish();throw new AssertionError("unexpected-completion");}catch(IllegalStateException expected){}
                need(threadMap.get(Thread.currentThread())==work && failures.get()==holder && Bindings.LatentRuntimeActivation.stops==1,"root-retains-without-retry");
            }
            case "fence-failure" -> {
                PostAckHooks.failure=original;PostAckHooks.fenceFailure=new IllegalStateException("fence-failure");
                try{Activation.timer(Activation.monotonicMillis()+1000);throw new AssertionError("expected-failure");}
                catch(IllegalStateException error){need(error==original,"fence-preserves-primary");}
                need((boolean)get("poisoned") && Bindings.LatentRuntimeActivation.timers()==1
                    && Bindings.LatentRuntimeActivation.stops==0,"failed-fence-keeps-host-owner");
                try{finish();throw new AssertionError("unexpected-completion");}catch(IllegalStateException expected){}
                need(threadMap.get(Thread.currentThread())==work && Bindings.LatentRuntimeActivation.stops==0,"failed-fence-no-retry");
            }
            case "reentrant-root" -> {
                PostAckHooks.failure=original;var rootError=new AtomicReference<Throwable>();
                Bindings.LatentRuntimeActivation.stopObservation=()->{try{finish();}catch(Throwable error){rootError.set(error);}};
                try{Activation.timer(Activation.monotonicMillis()+1000);throw new AssertionError("expected-failure");}
                catch(IllegalStateException error){need(error==original,"reentry-preserves-primary");}
                need(rootError.get() instanceof IllegalStateException && threadMap.get(Thread.currentThread())==work
                    && failures.get()!=null && Bindings.LatentRuntimeActivation.stops==1,"fenced-before-rollback");
            }
            case "missing-token" -> {
                Bindings.LatentRuntimeActivation.nullStartToken=true;
                try{Activation.timer(Activation.monotonicMillis()+1000);throw new AssertionError("expected-missing-token");}
                catch(IllegalStateException error){need(error.getMessage().equals("activation-runtime-timer-start-token"),"missing-token-shape");}
                need(failures.get()!=null && token(failures.get())==null && (boolean)get("poisoned")
                    && Bindings.LatentRuntimeActivation.timers()==1 && Bindings.LatentRuntimeActivation.stops==0,"missing-token-retained-not-guessed");
            }
            default -> throw new IllegalArgumentException("unknown mode");
        }
        System.out.println("TIMER_POST_ACK_CONTROL PASS "+args[0]);
    }
}
