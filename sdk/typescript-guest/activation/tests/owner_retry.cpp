// Execute the production timer/import/broker headers with finite JS/host doubles.
// Tests exact reservation identities, capture destruction, and failure fences;
// does not execute SpiderMonkey, a signed component, or Store destruction.
#include "../native_timers.h"
#include "../native_imports.h"
#include <array>
#include <cstdio>
#include <cstring>

using namespace lsf::typescript::activation;
namespace {
struct Owner { bool live=false; uint8_t kind=0; unsigned refunds=0, attempts=0; };
struct Wait { bool live=false, joined=false, cancelled=false; };
std::array<Owner,256> owners{};
std::array<Wait,32> waits{};
std::array<unsigned,8> counts{}, peaks{}, limits{16,2,2,16,8,8,8,64};
uint64_t generation=1, next_owner=1, refuse_id=0, last_native=0;
uint32_t next_wait=1;
int refuse_kind=-1, deny_kind=-1;
bool closed=false, immediate=true, deferred=false, refuse_stop=false, refuse_disposer=false, refuse_park=false;
unsigned registrations=0, starts=0, stops=0, nexts=0, drops=0, cancellations=0, set_new=0, set_drop=0, disposals=0;
unsigned import_dispatches=0;
jobs_event_t event{};
const char* selected=nullptr;
#define CHECK(condition) do { if (!(condition)) { std::fprintf(stderr,"%s:%d: %s\n",selected,__LINE__,#condition); return false; } } while(false)
bool allowed(JSContext*) { return true; }
BrokerPromiseAccounting::Phase selected_phase=BrokerPromiseAccounting::Phase::Activation;
BrokerPromiseAccounting::Phase phase(JSContext*) { return selected_phase; }
bool failure(latent_runtime_activation_error_t* e, uint8_t reason) { *e=reason; return false; }
bool valid(const latent_runtime_activation_token_t* t) {
  return t && t->generation==generation && t->id>0 && t->id<next_owner && owners[t->id].live;
}
unsigned all_live() { unsigned total=0; for (auto n:counts) total+=n; return total; }
bool dispose(uint32_t) { ++disposals; return !refuse_disposer; }
struct Environment {
  JSContext cx;
  BrokerAccounting jobs{allowed};
  BrokerPromiseAccounting native{phase,jobs};
  ReadinessSet readiness{native};
  Timers timers{jobs,native,readiness};
  Imports imports{jobs,native,readiness};
  JSObject callback;
  bool begin() { return jobs.beginRoot(&cx); }
  bool finish() {
    JS_ClearPendingException(&cx);
    CHECK(imports.cancelAll(&cx));
    CHECK(timers.cancel(&cx));
    CHECK(readiness.retire(&cx));
    if (!jobs.rootSettled()) CHECK(jobs.settleRoot(&cx));
    CHECK(!imports.hasPending() && !timers.hasPending() && native.liveNative()==0);
    CHECK(all_live()==0 && fixture::roots==0 && fixture::buffers==0);
    for (uint64_t id=1; id<next_owner; ++id) CHECK(owners[id].refunds==1);
    return true;
  }
  bool reserve(uint32_t& id) {
    return imports.reserve(&cx,4,16,ImportRawResult::I32,JS::HandleValueArray::empty(),id) &&
           imports.setDisposer(&cx,id,dispose,4);
  }
  bool returned(uint32_t id) {
    JS::RootedObject promise(&cx);
    return imports.beginLowering(&cx,id) && imports.started(&cx,id,JOBS_SUBTASK_RETURNED,&promise);
  }
};
Environment* nested=nullptr;
int32_t nested_id=0, neighbour_id=0;
bool nested_ok=false;
unsigned nested_error_behavior=0;
bool nested_clear(JSContext* cx) {
  const unsigned live=counts[7];
  nested_ok=nested->timers.clear(cx,nested_id) && counts[7]==live &&
      nested->timers.clear(cx,neighbour_id) && counts[7]+1==live && fixture::roots==1;
  return nested_ok;
}
bool nested_clear_refused(JSContext* cx) {
  nested_ok=!nested->timers.clear(cx,neighbour_id) && JS_IsExceptionPending(cx);
  if (nested_error_behavior != 1) JS_ClearPendingException(cx); // model a JS catch
  if (nested_error_behavior == 2) JS_ReportErrorASCII(cx,"original-callback-error");
  return nested_ok && nested_error_behavior == 0;
}
}
extern "C" {
bool latent_runtime_activation_register(latent_runtime_activation_owner_kind_t kind,
    latent_runtime_activation_token_t* parent,latent_runtime_activation_token_t* out,
    latent_runtime_activation_error_t* error) {
  ++registrations;
  if (kind>=counts.size() || kind==deny_kind || counts[kind]>=limits[kind] || next_owner==owners.size())
    return failure(error,LATENT_RUNTIME_ACTIVATION_ERROR_RESOURCE_EXHAUSTED);
  if ((parent && !valid(parent)) || (closed && !parent))
    return failure(error,LATENT_RUNTIME_ACTIVATION_ERROR_INVALID_TOKEN);
  const auto id=next_owner++; owners[id]={true,kind,0,0}; ++counts[kind];
  if (counts[kind]>peaks[kind]) peaks[kind]=counts[kind];
  if (kind==7) last_native=id;
  *out={generation,id}; return true;
}
bool latent_runtime_activation_park(latent_runtime_activation_token_t* t,latent_runtime_activation_error_t* e) {
  if (refuse_park) return failure(e,LATENT_RUNTIME_ACTIVATION_ERROR_UNAVAILABLE);
  return valid(t) || failure(e,LATENT_RUNTIME_ACTIVATION_ERROR_INVALID_TOKEN);
}
bool latent_runtime_activation_wake(latent_runtime_activation_token_t* t,latent_runtime_activation_error_t* e) {
  return valid(t) || failure(e,LATENT_RUNTIME_ACTIVATION_ERROR_INVALID_TOKEN);
}
bool latent_runtime_activation_settle(latent_runtime_activation_token_t* t,latent_runtime_activation_error_t* e) {
  if (!valid(t)) return failure(e,LATENT_RUNTIME_ACTIVATION_ERROR_INVALID_TOKEN);
  auto& owner=owners[t->id]; ++owner.attempts;
  if (t->id==refuse_id || owner.kind==refuse_kind)
    return failure(e,LATENT_RUNTIME_ACTIVATION_ERROR_UNAVAILABLE);
  --counts[owner.kind]; owner.live=false; ++owner.refunds; return true;
}
bool latent_runtime_activation_close(latent_runtime_activation_error_t*) { closed=true; return true; }
bool latent_runtime_activation_timer_start(uint64_t,uint64_t*,latent_runtime_activation_token_t* parent,
    latent_runtime_activation_token_t* out,latent_runtime_activation_error_t* e) {
  if (!latent_runtime_activation_register(5,parent,out,e)) return false;
  ++starts; return true;
}
bool latent_runtime_activation_timer_stop(latent_runtime_activation_token_t* t,latent_runtime_activation_error_t* e) {
  if (refuse_stop) return failure(e,LATENT_RUNTIME_ACTIVATION_ERROR_UNAVAILABLE);
  if (!latent_runtime_activation_settle(t,e)) return false;
  ++stops; return true;
}
jobs_subtask_status_t latent_runtime_activation_timer_next(latent_runtime_activation_token_t,
    latent_runtime_activation_result_u64_error_t* out) {
  ++nexts;
  *out={};
  if (immediate) return JOBS_SUBTASK_RETURNED;
  if (next_wait==waits.size()) std::abort();
  const auto id=next_wait++; waits[id].live=true; return (id<<4)|JOBS_SUBTASK_STARTED;
}
uint32_t lsf_async_subtask_cancel(uint32_t id) {
  if (!waits.at(id).live) std::abort();
  ++cancellations; waits[id].cancelled=true;
  return deferred ? SubtaskCancellationBlocked : JOBS_SUBTASK_STARTED_CANCELLED;
}
void jobs_subtask_drop(jobs_subtask_t id) {
  if (!waits.at(id).live || waits[id].joined) std::abort();
  waits[id].live=false; ++drops;
}
void jobs_waitable_join(uint32_t id,jobs_waitable_set_t set) {
  if (!waits.at(id).live) std::abort();
  waits[id].joined=set!=0;
}
jobs_waitable_set_t jobs_waitable_set_new() { ++set_new; return 1; }
void jobs_waitable_set_drop(jobs_waitable_set_t) {
  for (const auto& w:waits) if (w.joined) std::abort();
  ++set_drop;
}
void jobs_waitable_set_wait(jobs_waitable_set_t,jobs_event_t* out) { *out=event; event={}; }
void jobs_waitable_set_poll(jobs_waitable_set_t set,jobs_event_t* out) { jobs_waitable_set_wait(set,out); }
}
namespace {
bool timer_retry(bool clear) {
  Environment e; CHECK(e.begin()); int32_t a=0,b=0;
  CHECK(e.timers.start(&e.cx,&e.callback,{},0,false,&a)); const auto first=last_native;
  CHECK(e.timers.start(&e.cx,&e.callback,{},0,false,&b)); const auto second=last_native;
  refuse_kind=7;
  for (unsigned attempt=0; attempt<3; ++attempt) {
    JS_ClearPendingException(&e.cx);
    CHECK(!(clear ? e.timers.clear(&e.cx,attempt ? b : a) : e.timers.cancel(&e.cx)));
    CHECK(owners[first].live && owners[second].live && counts[7]==2);
    CHECK(fixture::roots==1 && owners[first].attempts==attempt+1 && owners[second].attempts==0);
    int32_t rejected=99; const auto admitted=registrations;
    CHECK(!e.timers.start(&e.cx,&e.callback,{},0,false,&rejected));
    CHECK(rejected==0 && registrations==admitted);
  }
  refuse_kind=-1; CHECK(e.finish());
  CHECK(starts==2 && stops==2 && fixture::calls==0);
  return true;
}
bool timer_capture(bool refused) {
  Environment e; CHECK(e.begin());
  fixture::fail_capture=true; refuse_kind=refused ? 7 : -1;
  int32_t id=99; JS::Value arg;
  CHECK(!e.timers.start(&e.cx,&e.callback,JS::HandleValueArray(&arg,1),0,false,&id));
  CHECK(id==0 && e.cx.exception && std::strcmp(e.cx.detail,"oom")==0);
  CHECK(starts==0 && stops==0 && fixture::roots==0 && set_new==0);
  CHECK(e.native.liveNative()==(refused ? 1u : 0u));
  refuse_kind=-1; CHECK(e.finish()); return true;
}
bool timer_pending() {
  Environment e; CHECK(e.begin()); immediate=false; deferred=true; int32_t id=0;
  CHECK(e.timers.start(&e.cx,&e.callback,{},0,false,&id));
  CHECK(set_new==1 && fixture::roots==1 && counts[7]==2);
  CHECK(!e.timers.cancel(&e.cx));
  CHECK(cancellations==1 && drops==0 && fixture::roots==1 && counts[7]==2);
  JS_ClearPendingException(&e.cx); CHECK(!e.timers.turn(&e.cx,false));
  CHECK(fixture::calls==0 && cancellations==1);
  event={JOBS_EVENT_SUBTASK,1,JOBS_SUBTASK_RETURNED}; // late success after stop
  JS_ClearPendingException(&e.cx); CHECK(e.readiness.dispatch(&e.cx,false));
  CHECK(e.finish()); CHECK(drops==1 && set_drop==1 && fixture::calls==0); return true;
}
bool timer_nested() {
  Environment e; CHECK(e.begin()); nested=&e;
  CHECK(e.timers.start(&e.cx,&e.callback,{},0,false,&nested_id));
  CHECK(e.timers.start(&e.cx,&e.callback,{},0,false,&neighbour_id));
  fixture::callback=nested_clear;
  CHECK(e.timers.turn(&e.cx,false)); CHECK(nested_ok && fixture::calls==1);
  fixture::callback=nullptr; nested=nullptr;
  CHECK(e.finish()); return true;
}
bool timer_caught_clear_refusal(bool native_ack, unsigned behavior) {
  Environment e; CHECK(e.begin()); nested=&e; nested_error_behavior=behavior;
  CHECK(e.timers.start(&e.cx,&e.callback,{},0,true,&nested_id));
  const auto interval_native=last_native, interval_timer=next_owner-1;
  CHECK(e.timers.start(&e.cx,&e.callback,{},0,false,&neighbour_id));
  const auto other_native=last_native, other_timer=next_owner-1;
  const auto next_before=nexts;
  const auto callback_task=next_owner;
  if (native_ack) refuse_id=other_native; else refuse_stop=true;
  fixture::callback=nested_clear_refused;
  const bool result=e.timers.turn(&e.cx,false);
  if (result || nexts!=next_before || !e.cx.exception)
    std::fprintf(stderr,"turn=%d next-before=%u next-after=%u exception=%d\n",
                 result,next_before,nexts,e.cx.exception);
  CHECK(!result && e.cx.exception && nested_ok && nexts==next_before && fixture::calls==1);
  if (behavior==1) CHECK(std::strcmp(e.cx.detail,native_ack ?
      "activation-runtime-promise-%s-denied:%u" : "activation-runtime-timer-%s-denied:%u")==0);
  if (behavior==2) CHECK(std::strcmp(e.cx.detail,"original-callback-error")==0);
  const bool interval_live=!native_ack || behavior==0;
  CHECK(owners[interval_native].live && owners[interval_timer].live==interval_live && owners[other_native].live);
  CHECK(owners[other_timer].live==!native_ack && counts[7]==2 &&
        counts[5]==static_cast<unsigned>(interval_live)+static_cast<unsigned>(!native_ack));
  CHECK(fixture::roots==(native_ack ? 1u : 2u));
  CHECK(!owners[callback_task].live && owners[callback_task].refunds==1 &&
        !owners[callback_task+1].live && owners[callback_task+1].refunds==1);
  if (native_ack) CHECK(owners[other_native].attempts==(behavior ? 2u : 1u) && owners[other_native].refunds==0);
  JS_ClearPendingException(&e.cx); int32_t rejected=99; const auto admitted=registrations;
  CHECK(!e.timers.start(&e.cx,&e.callback,{},0,false,&rejected));
  CHECK(rejected==0 && registrations==admitted);
  JS_ClearPendingException(&e.cx); CHECK(!e.timers.turn(&e.cx,false));
  CHECK(fixture::calls==1 && nexts==next_before);
  fixture::callback=nullptr; nested=nullptr; refuse_stop=false; refuse_id=0;
  CHECK(e.finish());
  CHECK(owners[interval_native].refunds==1 && owners[interval_timer].refunds==1 &&
        owners[other_native].refunds==1 && owners[other_timer].refunds==1);
  return true;
}
bool timer_limit() {
  Environment e; CHECK(e.begin()); limits[7]=1; int32_t first=0,second=99;
  CHECK(e.timers.start(&e.cx,&e.callback,{},0,false,&first));
  CHECK(!e.timers.start(&e.cx,&e.callback,{},0,false,&second));
  CHECK(second==0 && starts==1 && fixture::roots==1 && counts[7]==1);
  CHECK(e.finish()); return true;
}
bool import_retry(unsigned stage) {
  Environment e; CHECK(e.begin()); uint32_t first=0,second=0;
  CHECK(e.reserve(first)); CHECK(e.reserve(second));
  // Record Native, Task, Queue, lowering Native, Result are admitted in order.
  const uint64_t result=next_owner-1, native=result-1, record=result-4;
  refuse_id=stage==0 ? result : stage==1 ? native : record;
  for (unsigned attempt=0;attempt<3;++attempt) {
    JS_ClearPendingException(&e.cx); CHECK(!e.imports.cancelAll(&e.cx));
    CHECK(owners[refuse_id].live && owners[refuse_id].attempts==attempt+1);
    CHECK(fixture::buffers==2 && fixture::buffer_bytes==20 && fixture::roots==2);
    CHECK(owners[result].refunds==(stage>0 ? 1u:0u));
    CHECK(owners[native].refunds==(stage>1 ? 1u:0u));
  }
  refuse_id=0; CHECK(e.finish()); CHECK(fixture::resolutions==0); return true;
}
bool import_fence(const char* operation) {
  Environment e; CHECK(e.begin()); uint32_t earlier=0,later=0;
  CHECK(e.reserve(earlier));
  if (std::strcmp(operation,"lower")!=0) {
    CHECK(e.returned(earlier));
    if (std::strcmp(operation,"lift")==0) CHECK(e.imports.turn(&e.cx));
  }
  CHECK(e.reserve(later));
  refuse_id=next_owner-4; // later Task refuses logical completion first
  CHECK(!e.imports.cancelAll(&e.cx));
  JS_ClearPendingException(&e.cx); const auto resolved=fixture::resolutions;
  if (std::strcmp(operation,"turn")==0) CHECK(!e.imports.turn(&e.cx));
  else if (std::strcmp(operation,"lower")==0) CHECK(!e.imports.beginLowering(&e.cx,earlier));
  else { void* buffer=nullptr; CHECK(!e.imports.beginLifting(&e.cx,earlier,buffer)); CHECK(buffer==nullptr); }
  CHECK(e.cx.exception && fixture::resolutions==resolved);
  refuse_id=0; CHECK(e.finish()); return true;
}
bool import_partial(bool buffers) {
  Environment e; CHECK(e.begin()); uint32_t id=99;
  if (buffers) fixture::fail_allocation=2; else deny_kind=6;
  CHECK(!e.imports.reserve(&e.cx,4,16,ImportRawResult::I32,{},id));
  CHECK(id==0 && fixture::resolutions==0);
  if (!buffers) CHECK(fixture::allocations==0 && counts[7]==0);
  else CHECK(fixture::buffers==1 && fixture::buffer_bytes==16);
  deny_kind=-1; CHECK(e.finish()); return true;
}
bool import_readiness_denied() {
  Environment e; CHECK(e.begin()); uint32_t id=0; CHECK(e.reserve(id));
  // The generated adapter invokes its host import only after beginLowering.
  // Deny the readiness owner while both original record owners are live.
  limits[7]=counts[7];
  const bool begin=e.imports.beginLowering(&e.cx,id);
  if (begin) ++import_dispatches;
  CHECK(!begin && e.cx.exception && import_dispatches==0 && set_new==0 &&
        fixture::buffers==2 && fixture::roots==2 && counts[7]==2 && counts[6]==1);
  // This is the generated wrapper's ordinary finally for a failed begin.
  CHECK(e.imports.liftCompleted(&e.cx,id) && !e.imports.hasPending());
  CHECK(import_dispatches==0 && fixture::buffers==0 && fixture::roots==0);
  limits[7]=8; CHECK(e.finish()); return true;
}
bool import_immediate_readiness_retired() {
  Environment e; CHECK(e.begin()); uint32_t id=0; CHECK(e.reserve(id));
  CHECK(e.imports.beginLowering(&e.cx,id) && set_new==1 && counts[7]==3);
  const auto set_owner=last_native;
  JS::RootedObject promise(&e.cx); ++import_dispatches;
  CHECK(e.imports.started(&e.cx,id,JOBS_SUBTASK_RETURNED,&promise) && promise.get());
  CHECK(e.imports.turn(&e.cx) && fixture::resolutions==1);
  void* result=nullptr;
  CHECK(e.imports.beginLifting(&e.cx,id,result) && result &&
        e.imports.delivered(&e.cx,id) && e.imports.liftCompleted(&e.cx,id));
  CHECK(!e.imports.hasPending() && e.readiness.physical() && owners[set_owner].live &&
        counts[7]==1 && fixture::buffers==0 && fixture::roots==0);
  // The production timer turn retires an unused shared set without invoking
  // application code when neither a timer nor a joined subtask remains.
  CHECK(e.timers.turn(&e.cx,false) && !e.readiness.physical() &&
        !owners[set_owner].live && owners[set_owner].refunds==1 && set_drop==1);
  CHECK(e.finish()); return true;
}
bool import_start_refused(bool park, bool returned) {
  Environment e; CHECK(e.begin()); uint32_t id=0; CHECK(e.reserve(id));
  CHECK(e.imports.beginLowering(&e.cx,id));
  const bool readiness_before_dispatch=set_new==1 && counts[7]==3;
  const auto wait=next_wait++; waits[wait].live=true; ++import_dispatches;
  if (park) refuse_park=true; else refuse_kind=3;
  JS::RootedObject promise(&e.cx);
  CHECK(!e.imports.started(&e.cx,id,(wait<<4)|JOBS_SUBTASK_STARTED,&promise));
  CHECK(readiness_before_dispatch && e.cx.exception && !promise.get() && waits[wait].live && waits[wait].joined &&
        fixture::buffers==2 && fixture::roots==2 && counts[7]==3 && counts[6]==1);
  const char* original=e.cx.detail;
  deferred=true;
  // The generated wrapper's finally requests cancellation. The real host
  // still owns the result buffer until the selected terminal notification.
  CHECK(e.imports.liftCompleted(&e.cx,id));
  CHECK(e.cx.exception && e.cx.detail==original && cancellations==1 &&
        waits[wait].live && waits[wait].joined && drops==0 && disposals==0 &&
        fixture::buffers==2 && fixture::roots==2 && counts[7]==3 && counts[6]==1);
  refuse_park=false; refuse_kind=-1; JS_ClearPendingException(&e.cx);
  event={JOBS_EVENT_SUBTASK,wait,returned ? JOBS_SUBTASK_RETURNED : JOBS_SUBTASK_STARTED_CANCELLED};
  CHECK(e.readiness.dispatch(&e.cx,true) && e.imports.turn(&e.cx));
  CHECK(!e.imports.hasPending() && !waits[wait].live && !waits[wait].joined &&
        drops==1 && disposals==unsigned(returned) && fixture::rejections==0 && fixture::resolutions==0 &&
        fixture::buffers==0 && fixture::roots==0 && counts[7]==1 && counts[6]==0);
  CHECK(e.finish()); CHECK(import_dispatches==1 && set_drop==1); return true;
}
bool import_immediate_start_refused(bool park) {
  Environment e; CHECK(e.begin()); uint32_t id=0; CHECK(e.reserve(id));
  const auto result=next_owner-1, native=result-1, queued=result-2,
             task=result-3, record=result-4;
  CHECK(e.imports.beginLowering(&e.cx,id) && set_new==1 && counts[7]==3);
  const auto set_owner=last_native;
  if (park) refuse_park=true; else refuse_kind=3;
  JS::RootedObject promise(&e.cx); ++import_dispatches;
  CHECK(!e.imports.started(&e.cx,id,JOBS_SUBTASK_RETURNED,&promise));
  CHECK(e.cx.exception && !promise.get() && fixture::rejections==0 && fixture::resolutions==0 &&
        owners[result].live && owners[native].live && owners[record].live &&
        owners[queued].live && owners[task].live && owners[set_owner].live);
  const char* original=e.cx.detail;
  // The generated finally must dispose this produced result once. Refuse the
  // work ACK after disposal to check that a later retry never disposes twice.
  refuse_kind=3;
  CHECK(!e.imports.liftCompleted(&e.cx,id));
  CHECK(e.cx.exception && e.cx.detail==original && disposals==1 && drops==0 &&
        fixture::rejections==0 && fixture::resolutions==0 && fixture::buffers==2 &&
        fixture::roots==2 && owners[result].live && owners[native].live &&
        owners[record].live && owners[queued].live && owners[task].live && owners[set_owner].live);
  refuse_park=false; refuse_kind=-1; JS_ClearPendingException(&e.cx);
  CHECK(e.imports.turn(&e.cx));
  CHECK(!e.imports.hasPending() && disposals==1 && fixture::rejections==0 &&
        fixture::resolutions==0 && fixture::buffers==0 && fixture::roots==0 &&
        owners[result].refunds==1 && owners[native].refunds==1 && owners[record].refunds==1 &&
        owners[queued].refunds==1 && owners[task].refunds==1 && owners[set_owner].live);
  CHECK(e.timers.turn(&e.cx,false) && owners[set_owner].refunds==1 && set_drop==1);
  CHECK(e.finish()); CHECK(import_dispatches==1 && disposals==1); return true;
}
bool import_join_refused() {
  Environment e; CHECK(e.begin()); uint32_t id=0; CHECK(e.reserve(id));
  CHECK(e.imports.beginLowering(&e.cx,id) && set_new==1);
  // Inject loss of the pre-admitted set between synchronous bridge steps to
  // exercise the failure branch; normal lowering cannot run JS between them.
  CHECK(e.readiness.retire(&e.cx)); limits[7]=counts[7];
  const auto wait=next_wait++; waits[wait].live=true; ++import_dispatches;
  JS::RootedObject promise(&e.cx);
  CHECK(!e.imports.started(&e.cx,id,(wait<<4)|JOBS_SUBTASK_STARTED,&promise));
  CHECK(e.cx.exception && !promise.get() && waits[wait].live && !waits[wait].joined &&
        fixture::buffers==2 && fixture::roots==2 && counts[7]==2 && counts[6]==1);
  const char* original=e.cx.detail;
  deferred=true;
  CHECK(!e.imports.liftCompleted(&e.cx,id));
  CHECK(e.cx.exception && e.cx.detail==original && cancellations==1 && drops==0 &&
        waits[wait].live && !waits[wait].joined && fixture::buffers==2 &&
        fixture::roots==2 && counts[7]==2 && counts[6]==1);
  limits[7]=8; JS_ClearPendingException(&e.cx);
  CHECK(e.imports.turn(&e.cx) && waits[wait].joined && set_new==2);
  event={JOBS_EVENT_SUBTASK,wait,JOBS_SUBTASK_STARTED_CANCELLED};
  CHECK(e.readiness.dispatch(&e.cx,true) && e.imports.turn(&e.cx));
  CHECK(!e.imports.hasPending() && drops==1 && disposals==0 &&
        fixture::rejections==0 && fixture::resolutions==0 && fixture::buffers==0 &&
        fixture::roots==0 && counts[7]==1 && counts[6]==0);
  CHECK(e.finish()); CHECK(import_dispatches==1 && set_drop==2); return true;
}
bool import_quarantine() {
  Environment e; CHECK(e.begin()); uint32_t id=0; CHECK(e.reserve(id)); CHECK(e.returned(id));
  refuse_disposer=true;
  CHECK(!e.imports.cancelAll(&e.cx)); CHECK(disposals==1);
  const auto original=counts; const auto bytes=fixture::buffer_bytes;
  JS_ClearPendingException(&e.cx); CHECK(!e.imports.turn(&e.cx));
  CHECK(fixture::resolutions==0 && counts==original && fixture::buffer_bytes==bytes);
  refuse_disposer=false;
  JS_ClearPendingException(&e.cx); CHECK(!e.imports.cancelAll(&e.cx));
  CHECK(disposals==1 && counts==original && e.imports.hasPending());
  // No successful cleanup claim: original tokens remain paid, even at scope
  // exit. Only a real Store/host retirement observer could prove their refund.
  return true;
}
bool lazy() {
  Environment e;
  CHECK(registrations==0 && fixture::roots==0 && fixture::buffers==0 && set_new==0);
  CHECK(!e.imports.hasPending() && !e.timers.hasPending()); return true;
}
bool repeated() {
  for (unsigned invocation=0;invocation<12;++invocation) {
    Environment e; CHECK(e.begin()); int32_t id=0; uint32_t imported=0;
    CHECK(e.timers.start(&e.cx,&e.callback,{},0,false,&id)); CHECK(e.reserve(imported));
    auto stale=latent_runtime_activation_token_t{generation,last_native};
    CHECK(e.finish());
    ++generation; closed=false;
    latent_runtime_activation_error_t error{};
    CHECK(!latent_runtime_activation_settle(&stale,&error));
    CHECK(error==LATENT_RUNTIME_ACTIVATION_ERROR_INVALID_TOKEN && all_live()==0);
  }
  return true;
}
bool native_readmission(bool snapshot) {
  Environment e; CHECK(e.begin()); NativeOwner owner;
  CHECK(e.native.beforeAllocate(&e.cx,owner)); const auto original=owner.token;
  const auto admitted=registrations;
  if (snapshot) selected_phase=BrokerPromiseAccounting::Phase::CompilerSnapshot;
  CHECK(!e.native.beforeAllocate(&e.cx,owner));
  CHECK(owner.live && owner.token.id==original.id && owner.token.generation==original.generation &&
      registrations==admitted && e.native.liveNative()==1);
  selected_phase=BrokerPromiseAccounting::Phase::Activation;
  JS_ClearPendingException(&e.cx); CHECK(e.native.acknowledgeRetirement(&e.cx,owner));
  CHECK(e.finish()); return true;
}
bool accepted_after_root() {
  Environment e; CHECK(e.begin()); int32_t id=0;
  CHECK(e.timers.start(&e.cx,&e.callback,{},0,false,&id));
  CHECK(e.jobs.parkRoot(&e.cx) && e.jobs.settleRoot(&e.cx));
  CHECK(e.jobs.rootSettled() && e.timers.hasPending() && counts[7]==1);
  CHECK(e.timers.turn(&e.cx,false) && fixture::calls==1);
  CHECK(e.finish()); return true;
}
bool fail_callback(JSContext* cx) {
  if (std::strcmp(selected,"timer-exception")==0) JS_ReportErrorASCII(cx,"original-callback-error");
  return false;
}
bool failed_callback() {
  Environment e; CHECK(e.begin()); int32_t id=0;
  CHECK(e.timers.start(&e.cx,&e.callback,{},0,false,&id)); fixture::callback=fail_callback;
  CHECK(!e.timers.turn(&e.cx,false) && fixture::calls==1 && fixture::roots==0 && counts[7]==0);
  if (std::strcmp(selected,"timer-exception")==0)
    CHECK(e.cx.exception && std::strcmp(e.cx.detail,"original-callback-error")==0);
  else CHECK(!e.cx.exception); // false/no-pending model, NOT a Wasm trap
  CHECK(!e.timers.start(&e.cx,&e.callback,{},0,false,&id));
  CHECK(fixture::calls==1 && starts==1); fixture::callback=nullptr;
  CHECK(e.finish()); return true;
}
bool run(const char* name) {
  if (!std::strcmp(name,"timer-cancel-retry")) return timer_retry(false);
  if (!std::strcmp(name,"timer-clear-retry")) return timer_retry(true);
  if (!std::strcmp(name,"timer-capture-before-host")) return timer_capture(false);
  if (!std::strcmp(name,"timer-capture-refused-retirement")) return timer_capture(true);
  if (!std::strcmp(name,"timer-late-return")) return timer_pending();
  if (!std::strcmp(name,"timer-nested-clear")) return timer_nested();
  if (!std::strcmp(name,"timer-stop-refusal-caught")) return timer_caught_clear_refusal(false,0);
  if (!std::strcmp(name,"timer-stop-refusal-uncaught")) return timer_caught_clear_refusal(false,1);
  if (!std::strcmp(name,"timer-stop-refusal-rethrow")) return timer_caught_clear_refusal(false,2);
  if (!std::strcmp(name,"timer-native-refusal-caught")) return timer_caught_clear_refusal(true,0);
  if (!std::strcmp(name,"timer-native-refusal-uncaught")) return timer_caught_clear_refusal(true,1);
  if (!std::strcmp(name,"timer-native-refusal-rethrow")) return timer_caught_clear_refusal(true,2);
  if (!std::strcmp(name,"timer-native-limit")) return timer_limit();
  if (!std::strcmp(name,"import-result-retry")) return import_retry(0);
  if (!std::strcmp(name,"import-lowering-retry")) return import_retry(1);
  if (!std::strcmp(name,"import-record-retry")) return import_retry(2);
  if (!std::strcmp(name,"import-turn-fence")) return import_fence("turn");
  if (!std::strcmp(name,"import-lower-fence")) return import_fence("lower");
  if (!std::strcmp(name,"import-lift-fence")) return import_fence("lift");
  if (!std::strcmp(name,"import-partial-admission")) return import_partial(false);
  if (!std::strcmp(name,"import-partial-buffer")) return import_partial(true);
  if (!std::strcmp(name,"import-readiness-denied-before-dispatch")) return import_readiness_denied();
  if (!std::strcmp(name,"import-immediate-readiness-retired")) return import_immediate_readiness_retired();
  if (!std::strcmp(name,"import-park-refused-late-return")) return import_start_refused(true,true);
  if (!std::strcmp(name,"import-park-refused-late-cancel")) return import_start_refused(true,false);
  if (!std::strcmp(name,"import-queue-refused-late-return")) return import_start_refused(false,true);
  if (!std::strcmp(name,"import-queue-refused-late-cancel")) return import_start_refused(false,false);
  if (!std::strcmp(name,"import-park-refused-immediate-return")) return import_immediate_start_refused(true);
  if (!std::strcmp(name,"import-queue-refused-immediate-return")) return import_immediate_start_refused(false);
  if (!std::strcmp(name,"import-join-refusal-retains-subtask")) return import_join_refused();
  if (!std::strcmp(name,"import-disposer-quarantine")) return import_quarantine();
  if (!std::strcmp(name,"lazy-synchronous")) return lazy();
  if (!std::strcmp(name,"repeated-generations")) return repeated();
  if (!std::strcmp(name,"native-live-slot")) return native_readmission(false);
  if (!std::strcmp(name,"snapshot-live-slot")) return native_readmission(true);
  if (!std::strcmp(name,"accepted-after-root")) return accepted_after_root();
  if (!std::strcmp(name,"timer-false-return")) return failed_callback();
  if (!std::strcmp(name,"timer-exception")) return failed_callback();
  return false;
}
}
int main(int argc,char** argv) {
  if (argc!=2) return 2;
  selected=argv[1]; const bool passed=run(selected);
  std::printf("{\"case\":\"%s\",\"passed\":%s,\"engineQualified\":false,\"peakNativeOwners\":%u,\"peakLoweringBufferBytes\":%zu,\"callbacks\":%u,\"retainedOwners\":%u,\"timerManagerBytes\":%zu,\"importManagerBytes\":%zu,\"nativeAccountingBytes\":%zu}\n",
      selected,passed?"true":"false",peaks[7],fixture::peak_buffer_bytes,fixture::calls,all_live(),sizeof(Timers),sizeof(Imports),sizeof(BrokerPromiseAccounting));
  return passed?0:1;
}
