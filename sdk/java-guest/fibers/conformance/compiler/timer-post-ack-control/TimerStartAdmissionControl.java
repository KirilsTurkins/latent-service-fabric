import dev.latent.generated.Bindings;
import dev.latent.guest.Option;
import dev.latent.guest.runtime.Activation;
import dev.latent.guest.runtime.TimerStartHooks;
import java.lang.reflect.Field;
import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicReference;
/** Candidate controls with a private ledger and injected reentry, not a guest witness. */
public final class TimerStartAdmissionControl {
    static Field f(Class<?> t,String n)throws Exception{var x=t.getDeclaredField(n);x.setAccessible(true);return x;}
    static Object get(String n)throws Exception{return f(Activation.class,n).get(null);}
    static void set(String n,Object v)throws Exception{f(Activation.class,n).set(null,v);}
    static void need(boolean b,String why){if(!b)throw new AssertionError(why);}
    static void finish()throws Exception{var m=Activation.class.getDeclaredMethod("finishInvocation",boolean.class);m.setAccessible(true);try{m.invoke(null,true);}catch(java.lang.reflect.InvocationTargetException e){if(e.getCause() instanceof Exception x)throw x;if(e.getCause() instanceof Error x)throw x;throw e;}}
    static Object token(Object timer)throws Exception{return f(Activation.Lease.class,"token").get(timer);}
    static void uncertain(Object work,Field timer,boolean known)throws Exception{
        Object holder=timer.get(work);need(holder!=null && (boolean)f(holder.getClass(),"startPending").get(holder)
            && (boolean)f(holder.getClass(),"closing").get(holder) && (token(holder)!=null)==known
            && (int)get("pendingTimerStarts")==1 && (boolean)get("poisoned") && Bindings.LatentRuntimeActivation.stops==0,"uncertain-owner-retained");
    }
    @SuppressWarnings("unchecked") public static void main(String[]a)throws Exception{
        var rootToken=Bindings.LatentRuntimeActivation.register(Bindings.LatentRuntimeActivationOwnerKind.Task,Option.none()).value();
        var type=Class.forName("dev.latent.guest.runtime.Activation$Work");var ctor=type.getDeclaredConstructor(Bindings.LatentRuntimeActivationToken.class);ctor.setAccessible(true);Object work=ctor.newInstance(rootToken);
        var map=(Map<Thread,Object>)get("threads");map.put(Thread.currentThread(),work);set("root",work);set("entered",true);var timer=f(type,"timer");var timers=(List<?>)get("timers");
        switch(a[0]){
            case "normal" -> {
                long deadline=Activation.monotonicMillis()+1000;var lease=Activation.timer(deadline);
                need(timer.get(work)==lease && timers.contains(lease) && (int)get("pendingTimerStarts")==0
                    && !(boolean)f(lease.getClass(),"startPending").get(lease) && !(boolean)f(lease.getClass(),"closing").get(lease),"normal-publication");
                Activation.beginTimedFrame(lease);need(Activation.timerDeadline(-1)==deadline,"deadline");Activation.endTimedFrame(lease);
                lease.close();need(Bindings.LatentRuntimeActivation.timers()==0 && timer.get(work)==null && timers.isEmpty(),"ordinary-close");finish();
            }
            case "refusal" -> {
                Bindings.LatentRuntimeActivation.denyStart=true;
                try{Activation.timer(Activation.monotonicMillis()+1000);throw new AssertionError("unexpected-success");}catch(IllegalStateException e){need(e.getMessage().equals("activation-runtime-timer-start-ResourceExhausted"),"refusal-shape");}
                need(timer.get(work)==null && (int)get("pendingTimerStarts")==0 && !(boolean)get("poisoned")
                    && Bindings.LatentRuntimeActivation.stops==0 && Bindings.LatentRuntimeActivation.timers()==0,"refusal-released");
                Bindings.LatentRuntimeActivation.denyStart=false;var lease=Activation.timer(Activation.monotonicMillis()+1000);lease.close();finish();
            }
            case "lost-start" -> {
                var original=new IllegalStateException("lost-start-result");Bindings.LatentRuntimeActivation.startFailure=original;
                try{try{Activation.timer(Activation.monotonicMillis()+1000);}finally{Activation.finished(Thread.currentThread());}throw new AssertionError("unexpected-success");}
                catch(IllegalStateException e){need(e==original,"primary-error");}
                need(!(boolean)f(type,"complete").get(work) && Bindings.LatentRuntimeActivation.settlements==0 && Bindings.LatentRuntimeActivation.timers()==1,"work-not-settled");
                uncertain(work,timer,false);try{finish();throw new AssertionError("unexpected-finish");}catch(IllegalStateException expected){}need(map.get(Thread.currentThread())==work,"work-retained");
            }
            case "inflight-root" -> {
                var failure=new AtomicReference<Throwable>();Bindings.LatentRuntimeActivation.startObservation=()->{try{finish();}catch(Throwable e){failure.set(e);}};
                try{Activation.timer(Activation.monotonicMillis()+1000);throw new AssertionError("unexpected-success");}catch(IllegalStateException expected){}
                need(failure.get() instanceof IllegalStateException && map.get(Thread.currentThread())==work && get("root")==work
                    && Bindings.LatentRuntimeActivation.timers()==1,"root-retained-during-call");uncertain(work,timer,true);
            }
            case "inflight-worker" -> {
                var failure=new AtomicReference<Throwable>();Bindings.LatentRuntimeActivation.startObservation=()->{try{Activation.finished(Thread.currentThread());}catch(Throwable e){failure.set(e);}};
                try{Activation.timer(Activation.monotonicMillis()+1000);throw new AssertionError("unexpected-success");}catch(IllegalStateException expected){}
                need(failure.get()==null && !(boolean)f(type,"complete").get(work) && Bindings.LatentRuntimeActivation.settlements==0
                    && Bindings.LatentRuntimeActivation.timers()==1,"worker-not-settled");uncertain(work,timer,true);
            }
            case "same-work" -> {
                var nested=new AtomicReference<Throwable>();Bindings.LatentRuntimeActivation.startObservation=()->{
                    Bindings.LatentRuntimeActivation.startObservation=null;
                    try{Activation.timer(Activation.monotonicMillis()+1000);}catch(Throwable e){nested.set(e);}};
                var outer=Activation.timer(Activation.monotonicMillis()+1000);
                need(nested.get() instanceof IllegalStateException e && e.getMessage().equals("activation-runtime-timer-frame")
                    && Bindings.LatentRuntimeActivation.starts==1 && Bindings.LatentRuntimeActivation.timers()==1 && timer.get(work)==outer
                    && (int)get("pendingTimerStarts")==0,"same-work-rejected");outer.close();finish();
            }
            case "same-work-post-list" -> {
                TimerStartHooks.trigger="list";
                var nested=new AtomicReference<Throwable>();TimerStartHooks.reentryAction=()->{try{Activation.timer(Activation.monotonicMillis()+1000);}catch(Throwable e){nested.set(e);}};
                var outer=Activation.timer(Activation.monotonicMillis()+1000);
                need(nested.get() instanceof IllegalStateException e && e.getMessage().equals("activation-runtime-timer-frame")
                    && Bindings.LatentRuntimeActivation.starts==1 && timers.size()==1 && timer.get(work)==outer,"sentinel-before-list");outer.close();finish();
            }
            case "allocation-root" -> {
                TimerStartHooks.trigger="allocation";
                var failure=new AtomicReference<Throwable>();TimerStartHooks.reentryAction=()->{try{finish();}catch(Throwable e){failure.set(e);}};
                try{Activation.timer(Activation.monotonicMillis()+1000);throw new AssertionError("unexpected-success");}catch(IllegalStateException expected){}
                need(failure.get()==null && map.isEmpty() && get("root")==null && (int)get("pendingTimerStarts")==0
                    && Bindings.LatentRuntimeActivation.starts==0 && Bindings.LatentRuntimeActivation.timers()==0,"preclaim-root-does-not-admit");
            }
            case "lookup-root" -> {
                TimerStartHooks.trigger="allocation";
                var failure=new AtomicReference<Throwable>();TimerStartHooks.reentryAction=()->TimerStartHooks.lookupAction=()->{try{finish();}catch(Throwable e){failure.set(e);}};
                try{Activation.timer(Activation.monotonicMillis()+1000);throw new AssertionError("unexpected-success");}catch(IllegalStateException expected){}
                need(failure.get()==null && map.isEmpty() && get("root")==null && (int)get("pendingTimerStarts")==0
                    && Bindings.LatentRuntimeActivation.starts==0 && Bindings.LatentRuntimeActivation.timers()==0,"preclaim-lookup-does-not-admit");
            }
            case "preparation-root" -> {
                TimerStartHooks.trigger="clock";
                var failure=new AtomicReference<Throwable>();var sawSentinel=new AtomicReference<Boolean>();
                TimerStartHooks.reentryAction=()->{try{sawSentinel.set(timer.get(work)!=null && (int)get("pendingTimerStarts")==1);finish();}catch(Throwable e){failure.set(e);}};
                try{Activation.timer(Activation.monotonicMillis()+1000);throw new AssertionError("unexpected-success");}catch(IllegalStateException expected){}
                need(Boolean.TRUE.equals(sawSentinel.get()) && failure.get() instanceof IllegalStateException && map.get(Thread.currentThread())==work
                    && Bindings.LatentRuntimeActivation.starts==0 && Bindings.LatentRuntimeActivation.timers()==0 && (boolean)get("poisoned"),"preparation-root-fenced");
            }
            case "preparation-same-work" -> {
                TimerStartHooks.trigger="clock";
                var nested=new AtomicReference<Throwable>();TimerStartHooks.reentryAction=()->{try{Activation.timer(Activation.monotonicMillis()+1000);}catch(Throwable e){nested.set(e);}};
                var outer=Activation.timer(Activation.monotonicMillis()+1000);
                need(nested.get() instanceof IllegalStateException && Bindings.LatentRuntimeActivation.starts==1 && timer.get(work)==outer
                    && (int)get("pendingTimerStarts")==0,"preparation-sentinel-blocks-nested");outer.close();finish();
            }
            case "nested-distinct" -> {
                var nested=new AtomicReference<Activation.Lease>();var failure=new AtomicReference<Throwable>();var midway=new AtomicReference<Integer>();
                var token=Bindings.LatentRuntimeActivation.register(Bindings.LatentRuntimeActivationOwnerKind.Task,Option.none()).value();var other=ctor.newInstance(token);
                Bindings.LatentRuntimeActivation.startObservation=()->{
                    Bindings.LatentRuntimeActivation.startObservation=null;map.put(Thread.currentThread(),other);
                    try{nested.set(Activation.timer(Activation.monotonicMillis()+1000));midway.set((int)get("pendingTimerStarts"));}catch(Throwable e){failure.set(e);}
                    finally{map.put(Thread.currentThread(),work);}};
                var outer=Activation.timer(Activation.monotonicMillis()+1000);
                need(failure.get()==null && nested.get()!=null && midway.get()==1 && (int)get("pendingTimerStarts")==0
                    && timer.get(work)==outer && timer.get(other)==nested.get() && timers.size()==2,"distinct-counter");
                map.put(Thread.currentThread(),other);nested.get().close();map.put(Thread.currentThread(),work);outer.close();finish();
            }
            case "overflow" -> {
                set("pendingTimerStarts",Integer.MAX_VALUE);
                try{Activation.timer(Activation.monotonicMillis()+1000);throw new AssertionError("unexpected-success");}
                catch(IllegalStateException e){need(e.getMessage().equals("activation-runtime-timer-start-capacity"),"overflow-shape");}
                need(timer.get(work)==null && (int)get("pendingTimerStarts")==Integer.MAX_VALUE && (boolean)get("poisoned")
                    && Bindings.LatentRuntimeActivation.starts==0,"overflow-fenced");
            }
            case "settle-before-start" -> {
                var nested=new AtomicReference<Throwable>();Bindings.LatentRuntimeActivation.settleObservation=()->{try{Activation.timer(Activation.monotonicMillis()+1000);}catch(Throwable e){nested.set(e);}};
                Activation.finished(Thread.currentThread());need(nested.get() instanceof IllegalStateException && Bindings.LatentRuntimeActivation.starts==0
                    && (boolean)f(type,"complete").get(work),"finishing-work-rejects-start");finish();
            }
            case "settle-refusal-retry" -> {
                Bindings.LatentRuntimeActivation.denySettle=true;
                try{Activation.finished(Thread.currentThread());throw new AssertionError("unexpected-success");}catch(IllegalStateException e){need(e.getMessage().equals("activation-runtime-settle-Cancelled"),"settle-refusal");}
                need((boolean)f(type,"finishing").get(work) && (boolean)f(type,"finishRefused").get(work)
                    && !(boolean)get("poisoned"),"settle-refusal-fenced");
                try{Activation.timer(Activation.monotonicMillis()+1000);throw new AssertionError("timer-admitted-after-finish-refusal");}
                catch(IllegalStateException expected){}
                need(Bindings.LatentRuntimeActivation.starts==0,"finish-refusal-no-start");
                Bindings.LatentRuntimeActivation.denySettle=false;Activation.finished(Thread.currentThread());need((boolean)f(type,"complete").get(work),"settle-retry");finish();
            }
            case "settle-refusal-reentry" -> {
                var nested=new AtomicReference<Throwable>();var admitted=new AtomicReference<Activation.Lease>();
                Bindings.LatentRuntimeActivation.denySettle=true;
                TimerStartHooks.refusalAction=()->{try{admitted.set(Activation.timer(Activation.monotonicMillis()+1000));}catch(Throwable e){nested.set(e);}};
                try{Activation.finished(Thread.currentThread());throw new AssertionError("unexpected-success");}
                catch(IllegalStateException error){need(error.getMessage().equals("activation-runtime-settle-Cancelled"),"settle-refusal-shape");}
                need(nested.get() instanceof IllegalStateException && admitted.get()==null && Bindings.LatentRuntimeActivation.starts==0
                    && (boolean)f(type,"finishing").get(work) && (boolean)f(type,"finishRefused").get(work),"no-timer-during-refusal-unwind");
            }
            case "settle-lost-ack" -> {
                var original=new IllegalStateException("settle-lost");Bindings.LatentRuntimeActivation.settleFailure=original;Bindings.LatentRuntimeActivation.settleFailureAfter=true;
                try{Activation.finished(Thread.currentThread());throw new AssertionError("unexpected-success");}catch(IllegalStateException e){need(e==original,"settle-primary");}
                need((boolean)f(type,"finishing").get(work) && (boolean)get("poisoned"),"settle-fenced");
                try{Activation.finished(Thread.currentThread());throw new AssertionError("retry-allowed");}catch(IllegalStateException expected){}
                need(Bindings.LatentRuntimeActivation.settlements==1,"no-settlement-retry");
            }
            default -> throw new IllegalArgumentException("unknown mode");
        }
        System.out.println("START_ADMISSION_CANDIDATE PASS "+a[0]);
    }
}
