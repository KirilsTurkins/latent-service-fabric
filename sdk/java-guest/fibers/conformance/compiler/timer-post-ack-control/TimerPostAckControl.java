import dev.latent.generated.Bindings;
import dev.latent.guest.Option;
import dev.latent.guest.runtime.Activation;
import dev.latent.guest.runtime.PostAckHooks;
import java.lang.reflect.Field;
import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicReference;

/** Host-ledger projection; cleanup here models, rather than executes, Store teardown. */
public final class TimerPostAckControl {
    private static Field field(Class<?> type,String name)throws Exception{var f=type.getDeclaredField(name);f.setAccessible(true);return f;}
    private static Object get(String name)throws Exception{return field(Activation.class,name).get(null);}
    private static void set(String name,Object value)throws Exception{field(Activation.class,name).set(null,value);}
    private static void need(boolean condition,String why){if(!condition)throw new AssertionError(why);}
    private static void finish()throws Exception{
        var method=Activation.class.getDeclaredMethod("finishInvocation",boolean.class);method.setAccessible(true);
        try{method.invoke(null,true);}catch(java.lang.reflect.InvocationTargetException e){if(e.getCause() instanceof Exception x)throw x;if(e.getCause() instanceof Error x)throw x;throw e;}
    }
    private static void noAdmission()throws Exception{
        int before=Bindings.LatentRuntimeActivation.registrations;
        try{Activation.owner(Bindings.LatentRuntimeActivationOwnerKind.Task);throw new AssertionError("admission-allowed");}
        catch(IllegalStateException error){need(error.getMessage().equals("activation-runtime-poisoned-store"),"admission-error");}
        need(before==Bindings.LatentRuntimeActivation.registrations,"host-admission-dispatched");
        try{finish();throw new AssertionError("unexpected-completion");}catch(IllegalStateException expected){}
    }
    @SuppressWarnings("unchecked")
    public static void main(String[]args)throws Exception{
        var rootToken=Bindings.LatentRuntimeActivation.register(Bindings.LatentRuntimeActivationOwnerKind.Task,Option.none()).value();
        var workClass=Class.forName("dev.latent.guest.runtime.Activation$Work");
        var ctor=workClass.getDeclaredConstructor(Bindings.LatentRuntimeActivationToken.class);ctor.setAccessible(true);Object work=ctor.newInstance(rootToken);
        var threadMap=(Map<Thread,Object>)get("threads");threadMap.put(Thread.currentThread(),work);set("root",work);set("entered",true);
        var timerField=field(workClass,"timer");var timers=(List<?>)get("timers");
        var failed=(AtomicReference<Activation.Lease>)get("failedQueuedOwners");
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
                need(failed.get()==null && !(boolean)get("poisoned") && timers.isEmpty() && Bindings.LatentRuntimeActivation.stops==0,"refusal-not-poisoned");finish();
            }
            case "allocation-before-admission" -> {
                PostAckHooks.failure=original;PostAckHooks.beforeAllocation=true;
                try{Activation.timer(Activation.monotonicMillis()+1000);throw new AssertionError("expected-failure");}
                catch(IllegalStateException error){need(error==original,"allocation-primary");}
                need(Bindings.LatentRuntimeActivation.starts==0 && Bindings.LatentRuntimeActivation.timers()==0
                    && !(boolean)get("poisoned") && timers.isEmpty(),"no-host-admission");finish();
            }
            case "missing-token" -> {
                Bindings.LatentRuntimeActivation.nullStartToken=true;
                try{Activation.timer(Activation.monotonicMillis()+1000);throw new AssertionError("expected-missing-token");}
                catch(IllegalStateException error){need(error.getMessage().equals("activation-runtime-timer-start-token"),"missing-token-shape");}
                need((boolean)get("poisoned") && Bindings.LatentRuntimeActivation.timers()==1
                    && Bindings.LatentRuntimeActivation.stops==0 && failed.get()==null,"missing-token-host-retained");
                noAdmission();
            }
            case "before-list", "after-list" -> {
                PostAckHooks.failure=original;PostAckHooks.afterList=args[0].equals("after-list");
                try{Activation.timer(Activation.monotonicMillis()+1000);throw new AssertionError("expected-failure");}
                catch(IllegalStateException error){need(error==original,"primary-exception");}
                var tokens=Bindings.LatentRuntimeActivation.admittedTimers;
                need(tokens.size()==1 && Bindings.LatentRuntimeActivation.ownsTimer(tokens.get(0)) && (boolean)get("poisoned")
                    && Bindings.LatentRuntimeActivation.stops==0 && failed.get()==null,"host-owner-preserved");
                Object sentinel=timerField.get(work);
                need(timers.size()==(args[0].equals("after-list")?1:0) && sentinel!=null
                    && (boolean)field(sentinel.getClass(),"startPending").get(sentinel) && (int)get("pendingTimerStarts")==1,"local-publication-shape");
                noAdmission();
                need(threadMap.get(Thread.currentThread())==work && Bindings.LatentRuntimeActivation.ownsTimer(tokens.get(0)),"failed-root-preserves-host");
                // This is only a model of cancellation/drop, not a Store witness.
                Bindings.LatentRuntimeActivation.discardStore();
                need(Bindings.LatentRuntimeActivation.storeCancelled && !Bindings.LatentRuntimeActivation.ownsTimer(tokens.get(0)),"synthetic-cleanup");
            }
            case "list-allocation-failure" -> {
                var oom=new OutOfMemoryError("simulated-list-allocation");PostAckHooks.listFailure=oom;
                try{Activation.timer(Activation.monotonicMillis()+1000);throw new AssertionError("expected-oom");}
                catch(OutOfMemoryError error){need(error==oom,"allocation-error-primary");}
                var tokens=Bindings.LatentRuntimeActivation.admittedTimers;
                need(tokens.size()==1 && Bindings.LatentRuntimeActivation.ownsTimer(tokens.get(0)) && (boolean)get("poisoned")
                    && Bindings.LatentRuntimeActivation.stops==0 && failed.get()==null && timers.isEmpty(),"allocation-host-owner-preserved");
                noAdmission();
            }
            case "nested-after-list", "nested-failures" -> {
                var nestedError=new AtomicReference<Throwable>();
                var otherToken=Bindings.LatentRuntimeActivation.register(Bindings.LatentRuntimeActivationOwnerKind.Task,Option.none()).value();
                Object other=ctor.newInstance(otherToken);Thread otherKey=new Thread();threadMap.put(otherKey,other);
                Runnable nested=()->{
                    threadMap.put(Thread.currentThread(),other);PostAckHooks.failure=original;
                    try {Activation.timer(Activation.monotonicMillis()+1000);}catch(Throwable error){nestedError.set(error);}
                    finally {PostAckHooks.failure=null;threadMap.put(Thread.currentThread(),work);}
                };
                if(args[0].equals("nested-after-list"))PostAckHooks.afterListAction=nested;
                else Bindings.LatentRuntimeActivation.startObservation=nested;
                try{Activation.timer(Activation.monotonicMillis()+1000);throw new AssertionError("outer-unexpected-success");}
                catch(IllegalStateException expected){}
                var tokens=Bindings.LatentRuntimeActivation.admittedTimers;
                need(nestedError.get()==original && tokens.size()==2 && !tokens.get(0).equals(tokens.get(1))
                    && Bindings.LatentRuntimeActivation.ownsTimer(tokens.get(0)) && Bindings.LatentRuntimeActivation.ownsTimer(tokens.get(1))
                    && timerField.get(work)!=null && timerField.get(other)!=null && (int)get("pendingTimerStarts")==2
                    && Bindings.LatentRuntimeActivation.stops==0 && failed.get()==null && (boolean)get("poisoned"),"both-host-owners-retained");
                noAdmission();need(threadMap.get(otherKey)==other,"nested-work-retained");
            }
            default -> throw new IllegalArgumentException("unknown mode");
        }
        System.out.println("TIMER_POST_ACK_CONTROL PASS "+args[0]);
    }
}
