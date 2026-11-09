// Actual current Timers and extracted run_timer_turn, with finite JS/P3 doubles.
// This is not SpiderMonkey, real P3 execution, or signed guest qualification.
#include "sdk/typescript-guest/activation/native_timers.h"
#include "sdk/typescript-guest/activation/native_import_lifecycle.h"
#include <array>
#include <cstdio>
#include <cstring>
#include <memory>
using namespace lsf::typescript::activation;
unsigned rooted_callables=0;
bool call_succeeds=true, fail_next_capture=false;
static JSObject a,b,c;
static std::array<int,16> callbacks{};
static unsigned callback_count=0,polls=0,waits=0,drops=0,native_live=0;
static unsigned jobs_live=0,timer_live=0,next_timer=1,next_owner=20;
static bool pending_second=false,cancel_event=false;
static std::array<bool,4> joined{},events{};
static std::array<latent_runtime_activation_result_u64_error_t*,4> held_results{};
static Timers* callback_timers=nullptr;
static JSContext* callback_context=nullptr;
static int32_t first_id=0,second_id=0;
static unsigned clear_action=0;
static bool callback_clear_ok=true;
static void on_call(JSObject* value) {
  if(callback_count<callbacks.size()) callbacks[callback_count]=value==&a?1:value==&b?2:value==&c?3:0;
  ++callback_count;
  if(value==&a&&clear_action) {
    const auto id=clear_action==1?first_id:second_id;
    clear_action=0;
    callback_clear_ok=callback_timers->clear(callback_context,id);
  }
}
static bool allowed(JSContext*) {return true;}
extern "C" {
bool latent_runtime_activation_register(latent_runtime_activation_owner_kind_t,latent_runtime_activation_token_t* parent,latent_runtime_activation_token_t* output,latent_runtime_activation_error_t*) {
  if(!parent||!parent->generation||!parent->id)return false;
  *output={1,next_owner++};++jobs_live;return true;
}
bool latent_runtime_activation_park(latent_runtime_activation_token_t*,latent_runtime_activation_error_t*) {return true;}
bool latent_runtime_activation_wake(latent_runtime_activation_token_t*,latent_runtime_activation_error_t*) {return true;}
bool latent_runtime_activation_settle(latent_runtime_activation_token_t*,latent_runtime_activation_error_t*) {if(!jobs_live)return false;--jobs_live;return true;}
bool latent_runtime_activation_close(latent_runtime_activation_error_t*) {return true;}
bool latent_runtime_activation_timer_start(uint64_t,uint64_t*,latent_runtime_activation_token_t*,latent_runtime_activation_token_t* out,latent_runtime_activation_error_t*) {*out={1,next_timer++};++timer_live;return true;}
bool latent_runtime_activation_timer_stop(latent_runtime_activation_token_t*,latent_runtime_activation_error_t*) {if(!timer_live)return false;--timer_live;return true;}
jobs_subtask_status_t latent_runtime_activation_timer_next(latent_runtime_activation_token_t timer,latent_runtime_activation_result_u64_error_t* result) {
  if(timer.id==2&&pending_second){held_results[1]=result;return (1u<<4)|JOBS_SUBTASK_STARTED;}
  result->is_err=false;result->val.ok=0;return JOBS_SUBTASK_RETURNED;
}
uint32_t lsf_async_subtask_cancel(uint32_t) {return JOBS_SUBTASK_STARTED_CANCELLED;}
void jobs_subtask_drop(jobs_subtask_t) {++drops;}
void jobs_waitable_join(uint32_t handle,jobs_waitable_set_t set) {if(handle<joined.size())joined[handle]=set!=0;}
jobs_waitable_set_t jobs_waitable_set_new() {return 1;}
void jobs_waitable_set_drop(jobs_waitable_set_t) {}
void jobs_waitable_set_poll(jobs_waitable_set_t,jobs_event_t* event) {
  ++polls;*event={};
  for(unsigned id=1;id<events.size();++id) if(joined[id]&&events[id]) {
    if(held_results[id]){held_results[id]->is_err=false;held_results[id]->val.ok=0;}
    *event={JOBS_EVENT_SUBTASK,id,cancel_event?JOBS_SUBTASK_STARTED_CANCELLED:JOBS_SUBTASK_RETURNED};
    events[id]=false;return;
  }
}
void jobs_waitable_set_wait(jobs_waitable_set_t set,jobs_event_t* event) {++waits;jobs_waitable_set_poll(set,event);}
}
struct Native final:PromiseAccounting {
  uint64_t next=1;
  bool beforeAllocate(JSContext*,NativeOwner& owner) override {owner.token={2,next++};owner.live=true;++native_live;return true;}
  bool acknowledgeRetirement(JSContext*,NativeOwner& owner) override {if(owner.live){owner.live=false;--native_live;}return true;}
};
struct FakeImportAccounting final:ImportAccounting {
  uint64_t next=40;
  bool admit(JSContext*,JobOwners& work,NativeOwner& n,NativeOwner& r) override {
    work.task={1,next++};work.task_live=true;work.queued={1,next++};work.queued_live=true;jobs_live+=2;
    n.token={2,next++};n.live=true;r.token={2,next++};r.live=true;native_live+=2;return true;
  }
  bool rollback(JSContext*,JobOwners&,NativeOwner&,NativeOwner&) override {return false;}
  bool park(JSContext*,JobOwners& work) override {if(!work.queued_live)return false;work.queued_live=false;--jobs_live;return true;}
  bool resume(JSContext*,JobOwners&) override {return true;}
  bool complete(JSContext*,JobOwners& work) override {if(work.task_live){work.task_live=false;--jobs_live;}return true;}
  bool physicallyRetired(JSContext*,NativeOwner& n,NativeOwner& r) override {if(n.live){n.live=false;--native_live;}if(r.live){r.live=false;--native_live;}return true;}
};
struct Queue {bool ready=false;bool empty() const{return !ready;}bool isDrainingStopped() const{return false;}};
struct Imports {
  Queue& queue;ImportLifecycle* life=nullptr;ImportLifecycle* life2=nullptr;
  bool settled=false,settled2=false,enqueue=true;
  explicit Imports(Queue& q):queue(q){}
  bool turn(JSContext* cx) {
    const std::array<ImportLifecycle*,2> items{life,life2};
    const std::array<bool*,2> done{&settled,&settled2};
    for(unsigned i=0;i<items.size();++i){
      auto* item=items[i];if(!item)continue;
      if(item->phase()==ImportLifecycle::Phase::Pending&&!item->observe(cx))return false;
      if(item->phase()==ImportLifecycle::Phase::Returned&&!*done[i]){
        *done[i]=true;if(enqueue)queue.ready=true;return true;
      }
    }
    return true;
  }
  bool hasReady() const {
    return (life&&life->phase()==ImportLifecycle::Phase::Returned&&!settled)||
           (life2&&life2->phase()==ImportLifecycle::Phase::Returned&&!settled2);
  }
  bool hasPending() const {return life||life2;}
};
struct Partial {bool collect(JSContext*){return true;}bool hasPending() const{return false;}};
namespace lsf::typescript::activation {
static Native native;
static BrokerAccounting jobs(allowed);
static ReadinessSet readiness(native);
static Timers timers(jobs,native,readiness);
static Queue queue_value;static Queue* queue=&queue_value;
static Imports imports(queue_value);static Partial partial_own;
static bool effects_allowed(JSContext*) {return true;}
#include "run_timer_turn.inc"
}
int main(int argc,char** argv) {
  if(argc!=2)return 2;
  const bool immediate=std::strcmp(argv[1],"immediate")==0;
  const bool delivered=std::strcmp(argv[1],"delivered")==0;
  const bool queued=std::strcmp(argv[1],"queued")==0;
  const bool noevent=std::strcmp(argv[1],"noevent")==0;
  const bool selfclear=std::strcmp(argv[1],"selfclear")==0;
  const bool otherclear=std::strcmp(argv[1],"otherclear")==0;
  const bool import_ready=std::strcmp(argv[1],"import-ready")==0;
  const bool import_queued=std::strcmp(argv[1],"import-queued")==0;
  const bool cancellation=std::strcmp(argv[1],"cancelled")==0;
  const bool two_ready=std::strcmp(argv[1],"two-import-ready")==0;
  const bool two_nojob=std::strcmp(argv[1],"two-import-nojob")==0;
  const bool multi=two_ready||two_nojob;
  const bool import_case=import_ready||import_queued||multi;
  if(!immediate&&!delivered&&!queued&&!noevent&&!selfclear&&!otherclear&&!import_case&&!cancellation)return 2;
  pending_second=delivered||queued||noevent||cancellation;
  cancel_event=cancellation;
  JSContext cx;JS::call_observer=on_call;callback_timers=&timers;callback_context=&cx;
  if(!timers.start(&cx,&a,JS::HandleValueArray::empty(),1,true,&first_id))return 3;
  if(!import_case&&!timers.start(&cx,&b,JS::HandleValueArray::empty(),0,false,&second_id))return 3;
  FakeImportAccounting import_accounting;
  std::unique_ptr<ImportLifecycle> life,life2;
  if(import_case){
    life=std::make_unique<ImportLifecycle>(import_accounting,readiness);
    const auto first_status=two_nojob?JOBS_SUBTASK_RETURNED:(2u<<4)|JOBS_SUBTASK_STARTED;
    if(!life->reserve(&cx)||!life->beginLowering(&cx)||!life->started(&cx,first_status))return 4;
    imports.life=life.get();events[2]=!two_nojob;
    if(multi){
      life2=std::make_unique<ImportLifecycle>(import_accounting,readiness);
      const auto second_status=two_nojob?JOBS_SUBTASK_RETURNED:(3u<<4)|JOBS_SUBTASK_STARTED;
      if(!life2->reserve(&cx)||!life2->beginLowering(&cx)||!life2->started(&cx,second_status))return 4;
      imports.life2=life2.get();events[3]=!two_nojob;imports.enqueue=!two_nojob;
      if(two_ready){
        // The real host removes a delivered event even while its subtask
        // stays joined. A third empty poll must not redeliver either event.
        if(!readiness.dispatch(&cx,false)||!readiness.dispatch(&cx,false)||
           !readiness.dispatch(&cx,false)||events[2]||events[3]||!joined[2]||!joined[3]||drops)return 5;
      }
    }
  }
  if((pending_second&&!noevent))events[1]=true;
  if((delivered||import_ready)&&!readiness.dispatch(&cx,false))return 5;
  if(selfclear)clear_action=1;
  if(otherclear)clear_action=2;
  const unsigned before=polls;
  bool passed=true,checkpoint=false,retained=false;unsigned pump_polls=0;
  if(multi){
    const bool first=run_timer_turn(&cx);
    const bool first_order=two_ready ? (queue_value.ready&&callback_count==0) :
        (!queue_value.ready&&callback_count==1&&imports.hasReady());
    passed=first&&first_order&&imports.settled&&!imports.settled2;
    // Simulate the first real loop checkpoint, then observe the second import.
    queue_value.ready=false;
    const bool second=run_timer_turn(&cx);
    const bool second_order=two_ready ? (queue_value.ready&&callback_count==0) :
        (!queue_value.ready&&callback_count==2);
    checkpoint=two_ready&&first_order&&second_order;
    retained=life->hasPhysicalSubtask()&&life2->hasPhysicalSubtask()&&
        native_live>=5&&jobs_live>=2;
    passed=passed&&second&&second_order&&imports.settled2&&retained;
    pump_polls=polls-before;
    queue_value.ready=false;
    for(auto* item:{life.get(),life2.get()}){
      if(!item->beginLifting(&cx)||!item->liftCompleted(&cx))return 8;
    }
    ImportLifecycle::Retirement retirement1,retirement2;
    if(!life->releaseAfterPhysicalDestruction(&cx,retirement1)||
       !life2->releaseAfterPhysicalDestruction(&cx,retirement2))return 8;
    imports.life=imports.life2=nullptr;life.reset();life2.reset();
    if(!import_accounting.physicallyRetired(&cx,retirement1.native,retirement1.result)||
       !import_accounting.physicallyRetired(&cx,retirement2.native,retirement2.result))return 8;
    // No ready import remains to hold the early checkpoint condition true.
    if(!run_timer_turn(&cx))return 8;
    passed=passed&&(two_ready?callback_count==1:callback_count==3);
  }else if(import_case){
    if(import_queued){
      const bool turn=run_timer_turn(&cx);
      passed=turn&&callback_count==1&&polls==before+1&&joined[2]&&!events[2];
    }
    const auto count_before=callback_count;
    const bool turn=run_timer_turn(&cx);
    checkpoint=queue_value.ready&&callback_count==count_before&&life->phase()==ImportLifecycle::Phase::Returned;
    retained=joined[2]&&drops==0&&native_live>=3&&jobs_live>=1;
    passed=passed&&turn&&checkpoint&&retained;
    pump_polls=polls-before;
    // For baseline failures, explicitly deliver the modelled terminal event
    // for cleanup; this never changes the assertions or counts above.
    if(life->phase()==ImportLifecycle::Phase::Pending&&events[2]) {
      if(!readiness.dispatch(&cx,false)||!life->observe(&cx))return 7;
    }
    // Simulate the real loop's next js::RunJobs checkpoint and typed lift.
    queue_value.ready=false;
    if(!life->beginLifting(&cx)||!life->liftCompleted(&cx))return 8;
    ImportLifecycle::Retirement retiring;
    if(!life->releaseAfterPhysicalDestruction(&cx,retiring))return 8;
    imports.life=nullptr;life.reset();
    if(!import_accounting.physicallyRetired(&cx,retiring.native,retiring.result))return 8;
  }else if(cancellation){
    passed=run_timer_turn(&cx)&&!run_timer_turn(&cx)&&cx.exception&&callback_count==1;
    JS_ClearPendingException(&cx);
  }else{
    for(unsigned i=0;i<5;++i){
      if(!run_timer_turn(&cx)){passed=false;break;}
      if(otherclear&&i==0){int32_t third=0;if(!timers.start(&cx,&c,JS::HandleValueArray::empty(),0,false,&third))return 6;}
    }
    unsigned ca=0,cb=0,cc=0;
    for(unsigned i=0;i<callback_count&&i<callbacks.size();++i){ca+=callbacks[i]==1;cb+=callbacks[i]==2;cc+=callbacks[i]==3;}
    if(noevent)passed=passed&&ca==5&&cb==0&&polls-before==5&&joined[1]&&drops==0;
    else if(selfclear)passed=passed&&ca==1&&cb==1&&callback_clear_ok;
    else if(otherclear)passed=passed&&cb==0&&cc==1&&callback_clear_ok;
    else passed=passed&&ca==4&&cb==1;
  }
  if(!import_case)pump_polls=polls-before;
  const bool cleanup=timers.cancel(&cx)&&readiness.retire(&cx)&&!native_live&&!timer_live&&!jobs_live&&!rooted_callables;
  std::printf("{\"case\":\"%s\",\"callbacks\":%u,\"polls\":%u,\"waits\":%u,\"checkpoint\":%s,\"importRetained\":%s,\"clean\":%s,\"passed\":%s}\n",argv[1],callback_count,pump_polls,waits,checkpoint?"true":"false",retained?"true":"false",cleanup?"true":"false",passed&&cleanup?"true":"false");
  return passed&&cleanup?0:1;
}
