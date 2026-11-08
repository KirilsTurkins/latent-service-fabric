// Actual readiness, timer and import-lifecycle sources with serialized doubles.
// These controls do not execute SpiderMonkey, Wasm or a signed guest.
#include "../native_timers.h"
#include "../native_import_lifecycle.h"
#include <cstdio>
#include <cstring>
using namespace lsf::typescript::activation;
unsigned rooted_callables=0;
bool call_succeeds=true, fail_next_capture=false;
static unsigned timer_starts=0, timer_stops=0, subtask_cancels=0, subtask_drops=0, joins=0;
static jobs_subtask_status_t supplied_status=JOBS_SUBTASK_RETURNED;
static bool allowed(JSContext*) { return true; }
extern "C" {
bool latent_runtime_activation_register(latent_runtime_activation_owner_kind_t, latent_runtime_activation_token_t*, latent_runtime_activation_token_t*, latent_runtime_activation_error_t*) { return false; }
bool latent_runtime_activation_park(latent_runtime_activation_token_t*, latent_runtime_activation_error_t*) { return true; }
bool latent_runtime_activation_wake(latent_runtime_activation_token_t*, latent_runtime_activation_error_t*) { return true; }
bool latent_runtime_activation_settle(latent_runtime_activation_token_t*, latent_runtime_activation_error_t*) { return true; }
bool latent_runtime_activation_close(latent_runtime_activation_error_t*) { return true; }
bool latent_runtime_activation_timer_start(uint64_t,uint64_t*,latent_runtime_activation_token_t*,latent_runtime_activation_token_t* out,latent_runtime_activation_error_t*) { *out={1,7}; ++timer_starts; return true; }
bool latent_runtime_activation_timer_stop(latent_runtime_activation_token_t*,latent_runtime_activation_error_t*) { ++timer_stops; return true; }
jobs_subtask_status_t latent_runtime_activation_timer_next(latent_runtime_activation_token_t,latent_runtime_activation_result_u64_error_t* result) { result->is_err=false; result->val.ok=0; return supplied_status; }
uint32_t lsf_async_subtask_cancel(uint32_t) { ++subtask_cancels; return JOBS_SUBTASK_STARTED_CANCELLED; }
void jobs_subtask_drop(jobs_subtask_t) { ++subtask_drops; }
void jobs_waitable_join(uint32_t,jobs_waitable_set_t) { ++joins; }
jobs_waitable_set_t jobs_waitable_set_new() { return 1; }
void jobs_waitable_set_drop(jobs_waitable_set_t) {}
void jobs_waitable_set_wait(jobs_waitable_set_t,jobs_event_t*) {}
void jobs_waitable_set_poll(jobs_waitable_set_t,jobs_event_t*) {}
}
struct Native final : PromiseAccounting {
  unsigned live=0, admissions=0, acknowledgements=0;
  bool beforeAllocate(JSContext*,NativeOwner& owner) override { owner={{1,++admissions},true}; ++live; return true; }
  bool acknowledgeRetirement(JSContext*,NativeOwner& owner) override { if(owner.live) { owner.live=false; --live; ++acknowledgements; } return true; }
};
struct Import final : ImportAccounting {
  unsigned tasks=0,native=0,result=0,completions=0;
  bool admit(JSContext*,JobOwners& work,NativeOwner& a,NativeOwner& b) override { work.task_live=work.queued_live=true; ++tasks; a={{1,2},true}; b={{1,3},true}; ++native; ++result; return true; }
  bool rollback(JSContext*,JobOwners& work,NativeOwner& a,NativeOwner& b) override { if(work.task_live) { --tasks; work={}; } if(a.live) { --native; a.live=false; } if(b.live) { --result; b.live=false; } return true; }
  bool park(JSContext*,JobOwners& work) override { work.queued_live=false; return true; }
  bool resume(JSContext*,JobOwners&) override { return true; }
  bool complete(JSContext*,JobOwners& work) override { ++completions; if(work.task_live) { --tasks; work={}; } return true; }
  bool physicallyRetired(JSContext*,NativeOwner& a,NativeOwner& b) override { if(a.live) { --native; a.live=false; } if(b.live) { --result; b.live=false; } return true; }
};
int main(int argc,char** argv) {
  if(argc!=2) return 2;
  const char* name=argv[1];
  const bool unknown=std::strstr(name,"unknown")!=nullptr;
  const bool zero=std::strstr(name,"zero")!=nullptr;
  const bool valid=std::strcmp(name,"valid-immediate") == 0;
  if(!unknown && !zero && !valid) return 2;
  const bool starting=std::strstr(name,"starting")!=nullptr;
  supplied_status=unknown ? (((zero ? 0u : 7u)<<4)|15u)
      : zero ? (starting ? JOBS_SUBTASK_STARTING : JOBS_SUBTASK_STARTED) : JOBS_SUBTASK_RETURNED;
  JSContext cx; Native native; bool ok=false;
  if(std::strncmp(name,"subtask-",8)==0) {
    Subtask item;
    bool accepted=item.started(&cx,supplied_status);
    ReadinessSet readiness(native);
    JS_ClearPendingException(&cx);
    const bool joined=readiness.join(&cx,item);
    const bool restarted=item.started(&cx,JOBS_SUBTASK_RETURNED);
    const bool cancel=item.cancel(&cx), drop=item.drop(&cx);
    ok=!accepted && !joined && !restarted && !cancel && !drop && item.uncertain() &&
       item.unresolved() && !item.physical() && !item.pending() &&
       !item.resultReady() && !item.cancelledReady() &&
       subtask_cancels==0 && subtask_drops==0 && joins==0;
  } else if(std::strncmp(name,"import-",7)==0) {
    ReadinessSet readiness(native); Import accounting; ImportLifecycle item(accounting,readiness);
    const bool setup=item.reserve(&cx) && item.beginLowering(&cx);
    const bool accepted=item.started(&cx,supplied_status);
    JS_ClearPendingException(&cx);
    const bool cancelled=item.cancel(&cx);
    ImportLifecycle::Retirement retired;
    JS_ClearPendingException(&cx);
    const bool released=item.releaseAfterPhysicalDestruction(&cx,retired);
    ok=setup && !accepted && !cancelled && !released && item.hasUncertainSubtask() &&
       !item.hasPhysicalSubtask() && accounting.tasks==1 &&
       accounting.native==1 && accounting.result==1 && accounting.completions==0 &&
       subtask_cancels==0 && subtask_drops==0 && joins==0;
  } else if(std::strncmp(name,"timer-",6)==0 || valid) {
    BrokerAccounting jobs(allowed); Timers timers(jobs,native); JSObject callback; int32_t id=123;
    bool started=timers.start(&cx,&callback,JS::HandleValueArray::empty(),0,false,&id);
    JS_ClearPendingException(&cx);
    if(valid) {
      bool cleared=timers.clear(&cx,id);
      ok=started && id!=0 && cleared && !timers.hasPending() && native.live==0 &&
         native.acknowledgements==1 && timer_starts==1 && timer_stops==1 && subtask_cancels==0 && subtask_drops==0;
    } else {
      bool cancelled=timers.cancel(&cx);
      bool cancelled_again=timers.cancel(&cx);
      int32_t retry_id=123;
      bool retried=timers.start(&cx,&callback,JS::HandleValueArray::empty(),0,false,&retry_id);
      ok=!started && id==0 && !cancelled && !cancelled_again && !retried && retry_id==0 &&
         timers.hasPending() && native.live==1 && native.acknowledgements==0 &&
         timer_starts==1 && timer_stops==1 && rooted_callables==1 &&
         subtask_cancels==0 && subtask_drops==0 && joins==0;
    }
  }
  std::printf("{\"case\":\"%s\",\"passed\":%s,\"engineQualified\":false}\n",name,ok?"true":"false");
  return ok?0:1;
}
