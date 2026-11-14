// Actual Timers source under serialized JS and broker doubles.
// This is not a SpiderMonkey or signed guest qualification.
#include "../native_timers.h"
#include <cstdio>
#include <cstring>
using namespace lsf::typescript::activation;
unsigned rooted_callables=0;
bool call_succeeds=true, fail_next_capture=false;
static bool stop_refused=false;
static unsigned starts=0, stops=0, live_timers=0;
static uint64_t stopped_ids[4]{};
static uint64_t next_timer=1;
static bool allowed(JSContext*) { return true; }
extern "C" {
bool latent_runtime_activation_register(latent_runtime_activation_owner_kind_t, latent_runtime_activation_token_t*, latent_runtime_activation_token_t*, latent_runtime_activation_error_t*) { return false; }
bool latent_runtime_activation_park(latent_runtime_activation_token_t*, latent_runtime_activation_error_t*) { return true; }
bool latent_runtime_activation_wake(latent_runtime_activation_token_t*, latent_runtime_activation_error_t*) { return true; }
bool latent_runtime_activation_settle(latent_runtime_activation_token_t*, latent_runtime_activation_error_t*) { return true; }
bool latent_runtime_activation_close(latent_runtime_activation_error_t*) { return true; }
bool latent_runtime_activation_timer_start(uint64_t, uint64_t*, latent_runtime_activation_token_t*, latent_runtime_activation_token_t* out, latent_runtime_activation_error_t*) {
  *out={1,next_timer++}; ++starts; ++live_timers; return true;
}
bool latent_runtime_activation_timer_stop(latent_runtime_activation_token_t* token, latent_runtime_activation_error_t* error) {
  if (stops>=4) return false;
  stopped_ids[stops++]=token->id;
  if (stop_refused) { *error=LATENT_RUNTIME_ACTIVATION_ERROR_UNAVAILABLE; return false; }
  if (!live_timers) return false;
  --live_timers; return true;
}
jobs_subtask_status_t latent_runtime_activation_timer_next(latent_runtime_activation_token_t, latent_runtime_activation_result_u64_error_t* result) {
  result->is_err=false; result->val.ok=0; return JOBS_SUBTASK_RETURNED;
}
uint32_t lsf_async_subtask_cancel(uint32_t) { return JOBS_SUBTASK_STARTED_CANCELLED; }
void jobs_subtask_drop(jobs_subtask_t) {}
void jobs_waitable_join(uint32_t, jobs_waitable_set_t) {}
jobs_waitable_set_t jobs_waitable_set_new() { return 1; }
void jobs_waitable_set_drop(jobs_waitable_set_t) {}
void jobs_waitable_set_wait(jobs_waitable_set_t, jobs_event_t*) {}
void jobs_waitable_set_poll(jobs_waitable_set_t, jobs_event_t*) {}
}
struct Native final : PromiseAccounting {
  unsigned live=0, admissions=0, acknowledgements=0;
  uint64_t last_acknowledged=0;
  bool refuse_ack=false;
  bool beforeAllocate(JSContext*, NativeOwner& owner) override {
    owner.token={2,++admissions}; owner.live=true; ++live; return true;
  }
  bool acknowledgeRetirement(JSContext*, NativeOwner& owner) override {
    if (owner.live && refuse_ack) return false;
    if (owner.live) { last_acknowledged=owner.token.id; owner.live=false; --live; ++acknowledgements; }
    return true;
  }
};
int main(int argc,char** argv) {
  if (argc!=2) return 2;
  const bool refused=std::strcmp(argv[1],"refused-stop")==0;
  const bool refused_native=std::strcmp(argv[1],"refused-native-settlement")==0;
  if (!refused && !refused_native && std::strcmp(argv[1],"successful-cleanup")!=0) return 2;
  JSContext cx;
  Native native;
  BrokerAccounting jobs(allowed);
  Timers timers(jobs,native);
  JSObject callback;
  JS::Value value;
  JS::HandleValueArray one(&value,1);
  int32_t id=99;
  stop_refused=refused;
  native.refuse_ack=refused_native;
  fail_next_capture=true;
  const bool first=timers.start(&cx,&callback,one,0,false,&id);
  const bool first_valid=!first && id==0 && cx.exception && cx.detail &&
      std::strcmp(cx.detail,"oom")==0 && starts==1 && stops==1;
  const unsigned first_live=native.live;
  JS_ClearPendingException(&cx);
  int32_t later_id=0;
  const bool later=timers.start(&cx,&callback,JS::HandleValueArray::empty(),0,false,&later_id);
  const bool admission_valid=refused || refused_native
      ? (!later && later_id==0 && starts==1 && native.admissions==1 && first_live==1 && live_timers==(refused ? 1u : 0u))
      : (later && later_id!=0 && starts==2 && native.admissions==2 && first_live==0 && live_timers==1);
  JS_ClearPendingException(&cx);
  stop_refused=false;
  native.refuse_ack=false;
  const bool retired=timers.cancel(&cx) && !timers.hasPending() && live_timers==0 &&
      native.live==0 && rooted_callables==0 && native.acknowledgements==native.admissions;
  const bool stopped_exactly=stopped_ids[0]==1 &&
      (refused_native ? stops==1 : stops==2 && stopped_ids[1]==(refused ? 1u : 2u));
  const bool cleaned=retired && stopped_exactly && native.last_acknowledged==(refused || refused_native ? 1u : 2u);
  const bool passed=first_valid && admission_valid && cleaned;
  std::printf("{\"case\":\"%s\",\"passed\":%s,\"engineQualified\":false}\n",argv[1],passed?"true":"false");
  return passed?0:1;
}
