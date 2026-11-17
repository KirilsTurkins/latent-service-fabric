// Execute the production timer/import/broker headers with finite JS/host doubles.
// Tests exact reservation identities, capture destruction, and failure fences;
// does not execute SpiderMonkey, a signed component, or Store destruction.
#define LSF_TYPESCRIPT_PARTIAL_OWN_CONTROLS 1
#define LSF_TYPESCRIPT_BORROW_CONTROLS 1
#include "../native_timers.h"
#include "../native_import_partial.h"
#include <array>
#include <cstdio>
#include <cstring>
#include <new>

// Observe actual deletion of the selected production sidecar, before its host
// ACK. The finite fixture never writes a pointer or token to its output.
static const void* watched_sidecar=nullptr;
static bool watched_sidecar_deleted=false;
static bool fail_next_nothrow=false;
void* operator new(std::size_t n) {
  if (auto* p=std::malloc(n ? n : 1)) return p;
  throw std::bad_alloc();
}
void* operator new(std::size_t n,const std::nothrow_t&) noexcept {
  if (fail_next_nothrow) { fail_next_nothrow=false; return nullptr; }
  return std::malloc(n ? n : 1);
}
void operator delete(void* p) noexcept {
  if (p && p==watched_sidecar) watched_sidecar_deleted=true;
  std::free(p);
}
void operator delete(void* p,std::size_t) noexcept { ::operator delete(p); }
void operator delete(void* p,const std::nothrow_t&) noexcept { ::operator delete(p); }

using namespace lsf::typescript::activation;
namespace lsf::typescript::activation {
struct PartialOwnLiftControls {
  static bool hasNode(PartialOwnLifts& p, uint32_t id) { return p.find(id)!=nullptr; }
  static const void* node(PartialOwnLifts& p, uint32_t id) { return p.find(id); }
  static Token owner(PartialOwnLifts& p, uint32_t id) { return p.find(id)->owner.token; }
  static Token failedOwner(PartialOwnLifts& p) { return p.failed_owner_.token; }
};
struct ImportBorrowControls {
  static bool hasObservers(const Imports& imports) { return imports.observers_ || imports.observer_count_!=0; }
  static const void* observer(const Imports& imports) { return imports.observers_.get(); }
  static bool quarantined(const Imports& imports) { return imports.failed_observer_completion_; }
  static NativeOwner failedOwner(const Imports& imports) { return imports.failed_record_owner_; }
};
}
namespace {
struct Owner { bool live=false; uint8_t kind=0; unsigned refunds=0, attempts=0; };
struct Wait { bool live=false, joined=false, cancelled=false; };
std::array<Owner,256> owners{};
std::array<Wait,32> waits{};
std::array<unsigned,8> counts{}, peaks{}, limits{16,2,2,16,8,8,8,64};
uint64_t generation=1, next_owner=1, refuse_id=0, last_native=0;
uint64_t observed_record=0, observed_native=0, observed_result=0;
uint64_t observed_borrow=0;
bool borrow_destroyed_before_ack=false;
uint64_t observed_partial=0;
uint32_t observed_partial_id=0;
PartialOwnLifts* observed_partial_manager=nullptr;
bool partial_destroyed_before_ack=false;
JSContext* partial_reentry_cx=nullptr;
bool partial_reenter=false, partial_reentry_refused=false;
unsigned expected_roots_at_ack=0, expected_buffers_at_ack=0;
bool record_destroyed_before_ack=false, native_destroyed_before_ack=false, result_destroyed_before_ack=false;
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
bool partial_init(JSContext*) { return true; }
uint64_t partial_get(uint32_t) { return 0; }
bool partial_dispose(uint32_t,uint32_t,uint32_t) { ++disposals; return !refuse_disposer; }
bool partial_bind(JSContext* cx,PartialOwnLifts& partial,JSObject* prototype) {
  JS::HandleId symbol; symbol.value=1;
  return partial.begin(cx,2,1,1) && partial.bind(cx,12,4,1,0,0,1,prototype,symbol) && partial.seal(cx);
}
struct Environment {
  JSContext cx;
  BrokerAccounting jobs{allowed};
  BrokerPromiseAccounting native{phase,jobs};
  ReadinessSet readiness{native};
  Timers timers{jobs,native,readiness};
  Imports imports{jobs,native,readiness};
  PartialOwnLifts partial{imports,partial_init};
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
  if (t->id==observed_borrow)
    borrow_destroyed_before_ack=watched_sidecar_deleted && fixture::roots==0 && fixture::buffers==0;
  if (t->id==observed_partial && observed_partial_manager)
    partial_destroyed_before_ack=watched_sidecar_deleted &&
        !PartialOwnLiftControls::hasNode(*observed_partial_manager,observed_partial_id);
  if (t->id==observed_partial && partial_reenter) {
    partial_reenter=false;
    partial_reentry_refused=!observed_partial_manager->collectCancelled(partial_reentry_cx);
  }
  if (t->id==refuse_id || owner.kind==refuse_kind)
    return failure(e,LATENT_RUNTIME_ACTIVATION_ERROR_UNAVAILABLE);
  const bool physically_retired=fixture::roots==expected_roots_at_ack &&
      fixture::buffers==expected_buffers_at_ack;
  if (t->id==observed_record) record_destroyed_before_ack=physically_retired;
  if (t->id==observed_native) native_destroyed_before_ack=physically_retired;
  if (t->id==observed_result) result_destroyed_before_ack=physically_retired;
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
  observed_record=record; observed_native=native; observed_result=result;
  expected_roots_at_ack=2; expected_buffers_at_ack=2; // the other record remains live
  refuse_id=stage==0 ? result : stage==1 ? native : record;
  for (unsigned attempt=0;attempt<3;++attempt) {
    JS_ClearPendingException(&e.cx); CHECK(!e.imports.cancelAll(&e.cx));
    CHECK(owners[refuse_id].live && owners[refuse_id].attempts==attempt+1);
    CHECK(fixture::buffers==2 && fixture::buffer_bytes==20 && fixture::roots==2);
    CHECK(owners[result].refunds==(stage>0 ? 1u:0u));
    CHECK(owners[native].refunds==(stage>1 ? 1u:0u));
  }
  refuse_id=0; CHECK(e.finish());
  CHECK(fixture::resolutions==0 && record_destroyed_before_ack &&
        native_destroyed_before_ack && result_destroyed_before_ack);
  return true;
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
  if (buffers) {
    const auto record=next_owner;
    observed_record=record; observed_native=record+3; observed_result=record+4;
    expected_roots_at_ack=0; expected_buffers_at_ack=0;
    fixture::fail_allocation=2;
  } else deny_kind=6;
  CHECK(!e.imports.reserve(&e.cx,4,16,ImportRawResult::I32,{},id));
  CHECK(id==0 && fixture::resolutions==0);
  if (!buffers) CHECK(fixture::allocations==0 && counts[7]==0);
  else CHECK(fixture::buffers==0 && fixture::buffer_bytes==0 && fixture::roots==0 &&
             !owners[observed_record].live && !owners[observed_native].live &&
             !owners[observed_result].live && !e.imports.hasPending());
  if (buffers) {
    // Cleanup succeeded: catching the allocation error may admit fresh work.
    fixture::fail_allocation=0; JS_ClearPendingException(&e.cx); uint32_t retry=0;
    CHECK(e.reserve(retry) && e.returned(retry));
  }
  deny_kind=-1; CHECK(e.finish());
  if (buffers) CHECK(record_destroyed_before_ack && native_destroyed_before_ack && result_destroyed_before_ack);
  return true;
}
bool import_allocation_cleanup_fence(unsigned phase, bool refuse_task) {
  Environment e; CHECK(e.begin()); uint32_t id=99;
  const auto record=next_owner, task=record+1, queue=record+2,
             native=record+3, result=record+4;
  refuse_id=refuse_task ? task : queue;
  if (phase<2) fixture::fail_allocation=phase+1;
  else if (phase==2) fixture::fail_array=true;
  else fixture::fail_promise=true;
  const unsigned retained_buffers=phase==0 ? 0 : phase==1 ? 1 : 2;
  CHECK(!e.imports.reserve(&e.cx,4,16,ImportRawResult::I32,{},id));
  CHECK(id==0 && e.cx.exception && std::strcmp(e.cx.detail,"oom")==0 && import_dispatches==0);
  CHECK(owners[record].live && owners[native].live && owners[result].live &&
        owners[refuse_id].live && fixture::roots==2 && fixture::buffers==retained_buffers);
  const auto admitted=registrations;
  JS_ClearPendingException(&e.cx); uint32_t rejected=99;
  CHECK(!e.imports.reserve(&e.cx,4,16,ImportRawResult::I32,{},rejected));
  CHECK(rejected==0 && registrations==admitted && fixture::resolutions==0);
  for (unsigned attempt=0;attempt<2;++attempt) {
    const auto previous=owners[refuse_id].attempts;
    JS_ClearPendingException(&e.cx); CHECK(!e.imports.cancelAll(&e.cx));
    CHECK(owners[refuse_id].live && owners[refuse_id].attempts==previous+1 &&
          owners[refuse_id].refunds==0 && owners[record].live &&
          fixture::roots==2 && fixture::buffers==retained_buffers);
    if (refuse_task) CHECK(owners[queue].attempts==1 && owners[queue].refunds==1);
  }
  refuse_id=0; fixture::fail_allocation=0; CHECK(e.finish());
  CHECK(owners[record].refunds==1 && owners[task].refunds==1 && owners[queue].refunds==1 &&
        owners[native].refunds==1 && owners[result].refunds==1 && import_dispatches==0);
  return true;
}
bool import_allocation_ack_fence(unsigned stage) {
  Environment e; CHECK(e.begin()); uint32_t id=99;
  const auto record=next_owner, task=record+1, queue=record+2,
             native=record+3, result=record+4;
  observed_record=record; observed_native=native; observed_result=result;
  expected_roots_at_ack=0; expected_buffers_at_ack=0;
  refuse_id=stage==0 ? result : stage==1 ? native : record;
  fixture::fail_allocation=2;
  CHECK(!e.imports.reserve(&e.cx,4,16,ImportRawResult::I32,{},id));
  CHECK(id==0 && e.cx.exception && std::strcmp(e.cx.detail,"oom")==0 &&
        fixture::roots==0 && fixture::buffers==0 && owners[refuse_id].live);
  const auto admitted=registrations;
  JS_ClearPendingException(&e.cx); uint32_t rejected=99;
  CHECK(!e.imports.reserve(&e.cx,4,16,ImportRawResult::I32,{},rejected));
  CHECK(rejected==0 && registrations==admitted);
  for (unsigned attempt=0;attempt<2;++attempt) {
    const auto previous=owners[refuse_id].attempts;
    JS_ClearPendingException(&e.cx); CHECK(!e.imports.cancelAll(&e.cx));
    CHECK(owners[refuse_id].live && owners[refuse_id].attempts==previous+1 &&
          owners[refuse_id].refunds==0 && fixture::roots==0 && fixture::buffers==0 &&
          owners[result].refunds==(stage>0 ? 1u : 0u) &&
          owners[native].refunds==(stage>1 ? 1u : 0u));
  }
  refuse_id=0; fixture::fail_allocation=0; CHECK(e.finish());
  CHECK(owners[record].refunds==1 && owners[task].refunds==1 && owners[queue].refunds==1 &&
        owners[native].refunds==1 && owners[result].refunds==1 && import_dispatches==0 &&
        record_destroyed_before_ack && native_destroyed_before_ack && result_destroyed_before_ack);
  return true;
}
bool import_dispatched_cleanup_fence(bool direct) {
  Environment e; CHECK(e.begin()); uint32_t earlier=0,later=0;
  CHECK(e.reserve(earlier)); ++import_dispatches; CHECK(e.returned(earlier));
  CHECK(e.reserve(later)); ++import_dispatches; CHECK(e.returned(later));
  const auto task=next_owner-4;
  refuse_id=task;
  CHECK(!(direct ? e.imports.cancel(&e.cx,later) : e.imports.liftCompleted(&e.cx,later)));
  CHECK(e.cx.exception && disposals==1 && owners[task].live &&
        fixture::roots==4 && fixture::buffers==4 && fixture::resolutions==0 &&
        fixture::rejections==unsigned(direct));
  const auto admitted=registrations;
  JS_ClearPendingException(&e.cx); uint32_t rejected=99;
  CHECK(!e.imports.reserve(&e.cx,4,16,ImportRawResult::I32,{},rejected));
  CHECK(rejected==0 && registrations==admitted && import_dispatches==2);
  refuse_id=0; JS_ClearPendingException(&e.cx);
  CHECK(!e.imports.turn(&e.cx) && fixture::resolutions==0);
  CHECK(e.finish()); CHECK(disposals==2 && fixture::resolutions==0 &&
                           fixture::rejections==unsigned(direct) && import_dispatches==2);
  return true;
}
bool import_partial_rollback_retry(unsigned stage) {
  Environment e; CHECK(e.begin()); uint32_t id=99;
  // Existing admission order: record Native, Task, Queue, lowering Native;
  // the Result admission then fails before any buffer or subtask exists.
  const auto record=next_owner, task=record+1, queue=record+2, native=record+3;
  observed_record=record; observed_native=native;
  expected_roots_at_ack=0; expected_buffers_at_ack=0;
  deny_kind=6;
  refuse_id=stage==0 ? native : stage==1 ? queue : task;
  CHECK(!e.imports.reserve(&e.cx,4,16,ImportRawResult::I32,{},id));
  CHECK(id==0 && e.cx.exception && fixture::allocations==0 && fixture::buffers==0);
  CHECK(owners[record].live && owners[refuse_id].live && owners[refuse_id].refunds==0);
  CHECK(owners[native].refunds==0 &&
        owners[queue].refunds==(stage!=1 ? 1u:0u) &&
        owners[task].refunds==(stage==0 ? 1u:0u));
  const char* original=e.cx.detail;
  uint32_t rejected=99; const auto admitted=registrations;
  CHECK(!e.imports.reserve(&e.cx,4,16,ImportRawResult::I32,{},rejected));
  CHECK(rejected==0 && registrations==admitted && e.cx.detail==original);
  for (unsigned attempt=0;attempt<2;++attempt) {
    const auto previous=owners[refuse_id].attempts;
    JS_ClearPendingException(&e.cx);
    CHECK(!e.imports.cancelAll(&e.cx));
    CHECK(owners[refuse_id].live && owners[refuse_id].attempts==previous+1 &&
          owners[refuse_id].refunds==0 && owners[record].live);
    CHECK(fixture::buffers==0 && fixture::roots==(stage==0 ? 0u:2u) && import_dispatches==0);
    CHECK(owners[native].refunds==0);
    if (stage!=1) CHECK(owners[queue].attempts==1 && owners[queue].refunds==1);
    if (stage==0) CHECK(owners[task].attempts==1 && owners[task].refunds==1);
  }
  deny_kind=-1; refuse_id=0; CHECK(e.finish());
  CHECK(owners[record].refunds==1 && owners[task].refunds==1 &&
        owners[queue].refunds==1 && owners[native].refunds==1 &&
        record_destroyed_before_ack && native_destroyed_before_ack);
  return true;
}
bool import_partial_admission_physical_order() {
  Environment e; CHECK(e.begin()); uint32_t id=99;
  const auto record=next_owner, task=record+1, queue=record+2, native=record+3;
  observed_record=record; observed_native=native;
  expected_roots_at_ack=0; expected_buffers_at_ack=0;
  deny_kind=6; // Result never admitted; no buffer has been allocated.
  CHECK(!e.imports.reserve(&e.cx,4,16,ImportRawResult::I32,{},id));
  CHECK(id==0 && fixture::allocations==0 && fixture::roots==0 && !e.imports.hasPending());
  CHECK(owners[record].refunds==1 && owners[task].refunds==1 && owners[queue].refunds==1 &&
        owners[native].refunds==1 && record_destroyed_before_ack && native_destroyed_before_ack);
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
  CHECK(!e.imports.turn(&e.cx)); JS_ClearPendingException(&e.cx);
  CHECK(e.imports.cancelAll(&e.cx));
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
  CHECK(!e.imports.turn(&e.cx)); JS_ClearPendingException(&e.cx);
  CHECK(!e.imports.cancelAll(&e.cx) && waits[wait].joined && set_new==2);
  event={JOBS_EVENT_SUBTASK,wait,JOBS_SUBTASK_STARTED_CANCELLED};
  CHECK(e.readiness.dispatch(&e.cx,true) && e.imports.cancelAll(&e.cx));
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
bool partial_cancel_undispatched() {
  Environment e; CHECK(e.begin()); uint32_t id=0;
  CHECK(partial_bind(&e.cx,e.partial,&e.callback));
  CHECK(e.reserve(id) && e.partial.prepare(&e.cx,id,12,partial_get,partial_dispose,1));
  const auto sidecar=PartialOwnLiftControls::owner(e.partial,id).id;
  observed_partial=sidecar; observed_partial_id=id; observed_partial_manager=&e.partial;
  watched_sidecar=PartialOwnLiftControls::node(e.partial,id);
  CHECK(owners[sidecar].live && PartialOwnLiftControls::hasNode(e.partial,id));
  CHECK(!e.partial.collectCancelled(&e.cx) && e.partial.collect(&e.cx));
  e.partial.cancelAll();
  CHECK(e.imports.cancelAll(&e.cx));
  CHECK(!e.imports.hasPending() && PartialOwnLiftControls::hasNode(e.partial,id) &&
        owners[sidecar].live && fixture::buffers==0 && fixture::roots==0 && disposals==0);
  CHECK(e.partial.collectCancelled(&e.cx));
  CHECK(!e.partial.hasPending() && !owners[sidecar].live && owners[sidecar].refunds==1 &&
        partial_destroyed_before_ack && disposals==0);
  CHECK(e.imports.cancelAll(&e.cx) && e.partial.collectCancelled(&e.cx) && owners[sidecar].attempts==1);
  uint32_t rejected=99; const auto admitted=registrations;
  CHECK(!e.imports.reserve(&e.cx,4,16,ImportRawResult::I32,{},rejected));
  CHECK(rejected==0 && registrations==admitted && !e.imports.hasPending());
  CHECK(e.finish()); return true;
}
bool borrow_unallocated_retry(bool refused) {
  Environment e; CHECK(e.begin()); uint32_t id=0; CHECK(e.reserve(id));
  const auto owner=next_owner, before_objects=fixture::object_count;
  JS::RootedObject handle(&e.cx);
  fail_next_nothrow=true;
  CHECK(!e.imports.watchBorrow(&e.cx,id,&handle));
  CHECK(!fail_next_nothrow && !handle.get() && e.cx.exception &&
        std::strcmp(e.cx.detail,"oom")==0 && fixture::object_count==before_objects &&
        !ImportBorrowControls::hasObservers(e.imports) && owners[owner].live &&
        ImportBorrowControls::failedOwner(e.imports).token.id==owner && import_dispatches==0);
  uint32_t rejected=99; const auto admitted=registrations;
  CHECK(!e.imports.reserve(&e.cx,4,16,ImportRawResult::I32,{},rejected) && rejected==0 &&
        registrations==admitted && std::strcmp(e.cx.detail,"oom")==0);
  CHECK(!e.imports.turn(&e.cx) && std::strcmp(e.cx.detail,"oom")==0);
  // The ordinary generated finally cancels the reserved import while its
  // original OOM is pending. No observer allocation or handle ever existed.
  refuse_id=refused ? owner : 0;
  const bool first=e.imports.liftCompleted(&e.cx,id);
  CHECK(first==!refused && e.cx.exception && std::strcmp(e.cx.detail,"oom")==0);
  if (refused) {
    CHECK(!ImportBorrowControls::quarantined(e.imports) && owners[owner].live &&
          owners[owner].attempts==1 && fixture::buffers==2 && fixture::roots==2);
    for (unsigned attempt=2;attempt<=3;++attempt) {
      JS_ClearPendingException(&e.cx);
      CHECK(!e.imports.cancelAll(&e.cx));
      const auto retained=ImportBorrowControls::failedOwner(e.imports);
      CHECK(retained.live && retained.token.id==owner && retained.token.generation==generation &&
            owners[owner].live && owners[owner].attempts==attempt && owners[owner].refunds==0 &&
            fixture::buffers==2 && fixture::roots==2 && import_dispatches==0);
    }
    refuse_id=0; JS_ClearPendingException(&e.cx); CHECK(e.imports.cancelAll(&e.cx));
  }
  CHECK(!e.imports.hasPending() && !owners[owner].live && owners[owner].refunds==1 &&
        owners[owner].attempts==(refused ? 4u:1u) && fixture::buffers==0 && fixture::roots==0);
  JS_ClearPendingException(&e.cx); CHECK(e.imports.cancelAll(&e.cx));
  CHECK(owners[owner].attempts==(refused ? 4u:1u) && import_dispatches==0 && disposals==0);
  CHECK(e.finish()); return true;
}
bool borrow_partial_setup_quarantine() {
  Environment e; CHECK(e.begin()); uint32_t id=0; CHECK(e.reserve(id));
  const auto owner=next_owner; JS::RootedObject handle(&e.cx);
  fixture::fail_promise=true;
  CHECK(!e.imports.watchBorrow(&e.cx,id,&handle) && !handle.get() && e.cx.exception &&
        ImportBorrowControls::hasObservers(e.imports) && ImportBorrowControls::quarantined(e.imports));
  CHECK(owners[owner].live && owners[owner].attempts==0 && fixture::buffers==2 && fixture::roots==3);
  CHECK(!e.imports.liftCompleted(&e.cx,id));
  for (unsigned attempt=0;attempt<2;++attempt) {
    JS_ClearPendingException(&e.cx); CHECK(!e.imports.cancelAll(&e.cx));
    CHECK(owners[owner].live && owners[owner].attempts==0 && fixture::buffers==2 &&
          fixture::roots==3 && import_dispatches==0 && disposals==0);
  }
  return true; // An allocated, partially initialized observer stays quarantined.
}
bool borrow_published_release() {
  Environment e; CHECK(e.begin()); uint32_t id=0; CHECK(e.reserve(id));
  const auto owner=next_owner; JS::RootedObject handle(&e.cx),promise(&e.cx),again(&e.cx);
  CHECK(e.imports.watchBorrow(&e.cx,id,&handle) && handle.get() &&
        e.imports.observeBorrow(&e.cx,handle,false,&promise) && promise.get());
  watched_sidecar=ImportBorrowControls::observer(e.imports); observed_borrow=owner;
  CHECK(watched_sidecar && owners[owner].live && e.imports.cancel(&e.cx,id));
  CHECK(!e.imports.hasPending() && borrow_destroyed_before_ack && owners[owner].refunds==1 &&
        fixture::resolutions==1 && !ImportBorrowControls::hasObservers(e.imports));
  CHECK(e.imports.observeBorrow(&e.cx,handle,false,&again) && again.get()==promise.get() &&
        fixture::resolutions==1 && owners[owner].attempts==1);
  CHECK(e.finish()); return true;
}
bool partial_cancel_retry() {
  Environment e; CHECK(e.begin()); uint32_t first=0,second=0;
  CHECK(partial_bind(&e.cx,e.partial,&e.callback));
  CHECK(e.reserve(first) && e.partial.prepare(&e.cx,first,12,partial_get,partial_dispose,1));
  const auto a=PartialOwnLiftControls::owner(e.partial,first);
  CHECK(e.reserve(second) && e.partial.prepare(&e.cx,second,12,partial_get,partial_dispose,1));
  const auto b=PartialOwnLiftControls::owner(e.partial,second);
  observed_partial=b.id; observed_partial_id=second; observed_partial_manager=&e.partial;
  watched_sidecar=PartialOwnLiftControls::node(e.partial,second);
  e.partial.cancelAll(); CHECK(e.imports.cancelAll(&e.cx));
  refuse_id=b.id;
  for (unsigned attempt=1; attempt<=3; ++attempt) {
    JS_ClearPendingException(&e.cx);
    CHECK(!e.partial.collectCancelled(&e.cx));
    const auto retained=PartialOwnLiftControls::failedOwner(e.partial);
    CHECK(retained.id==b.id && retained.generation==b.generation && owners[b.id].live &&
          owners[b.id].attempts==attempt && owners[b.id].refunds==0 && partial_destroyed_before_ack &&
          !PartialOwnLiftControls::hasNode(e.partial,second) && PartialOwnLiftControls::hasNode(e.partial,first) &&
          owners[a.id].live && owners[a.id].attempts==0 && fixture::buffers==0 && disposals==0);
  }
  refuse_id=0; JS_ClearPendingException(&e.cx);
  CHECK(e.imports.cancelAll(&e.cx) && e.partial.collectCancelled(&e.cx));
  CHECK(!e.partial.hasPending() && owners[b.id].attempts==4 && owners[b.id].refunds==1 &&
        owners[a.id].attempts==1 && owners[a.id].refunds==1 && disposals==0);
  CHECK(e.partial.collectCancelled(&e.cx) && owners[b.id].attempts==4 && owners[a.id].attempts==1);
  CHECK(e.finish()); return true;
}
bool partial_cancel_pending() {
  Environment e; CHECK(e.begin()); uint32_t id=0;
  CHECK(partial_bind(&e.cx,e.partial,&e.callback));
  CHECK(e.reserve(id) && e.partial.prepare(&e.cx,id,12,partial_get,partial_dispose,1));
  const auto sidecar=PartialOwnLiftControls::owner(e.partial,id).id;
  CHECK(e.imports.beginLowering(&e.cx,id));
  const auto wait=next_wait++; waits[wait].live=true; ++import_dispatches;
  JS::RootedObject promise(&e.cx);
  CHECK(e.imports.started(&e.cx,id,(wait<<4)|JOBS_SUBTASK_STARTED,&promise));
  deferred=true; e.partial.cancelAll();
  CHECK(!e.imports.cancelAll(&e.cx) && !e.partial.collectCancelled(&e.cx));
  CHECK(e.imports.hasPending() && PartialOwnLiftControls::hasNode(e.partial,id) && owners[sidecar].live &&
        owners[sidecar].attempts==0 && waits[wait].live && waits[wait].joined && drops==0 &&
        fixture::buffers==2 && disposals==0);
  event={JOBS_EVENT_SUBTASK,wait,JOBS_SUBTASK_STARTED_CANCELLED};
  CHECK(e.readiness.dispatch(&e.cx,true));
  CHECK(e.imports.cancelAll(&e.cx) && e.partial.collectCancelled(&e.cx));
  CHECK(!e.imports.hasPending() && !e.partial.hasPending() && !waits[wait].live && drops==1 &&
        !owners[sidecar].live && owners[sidecar].refunds==1 && disposals==0);
  CHECK(e.finish()); return true;
}
bool partial_cancel_returned() {
  Environment e; CHECK(e.begin()); uint32_t id=0;
  CHECK(partial_bind(&e.cx,e.partial,&e.callback));
  CHECK(e.reserve(id) && e.partial.prepare(&e.cx,id,12,partial_get,partial_dispose,1));
  const auto sidecar=PartialOwnLiftControls::owner(e.partial,id).id;
  CHECK(e.returned(id)); e.partial.cancelAll();
  CHECK(e.imports.cancelAll(&e.cx) && e.partial.collectCancelled(&e.cx));
  CHECK(disposals==1 && !e.partial.hasPending() && owners[sidecar].refunds==1);
  CHECK(e.imports.cancelAll(&e.cx) && e.partial.collectCancelled(&e.cx) && disposals==1);
  CHECK(e.finish()); return true;
}
bool partial_regular_ack_retry() {
  Environment e; CHECK(e.begin()); uint32_t id=0;
  CHECK(partial_bind(&e.cx,e.partial,&e.callback));
  CHECK(e.reserve(id) && e.partial.prepare(&e.cx,id,12,partial_get,partial_dispose,1));
  const auto owner=PartialOwnLiftControls::owner(e.partial,id);
  observed_partial=owner.id; observed_partial_id=id; observed_partial_manager=&e.partial;
  watched_sidecar=PartialOwnLiftControls::node(e.partial,id);
  CHECK(e.imports.cancel(&e.cx,id) && !e.imports.hasPending());
  refuse_id=owner.id;
  CHECK(!e.partial.collect(&e.cx) && partial_destroyed_before_ack && owners[owner.id].live);
  CHECK(PartialOwnLiftControls::failedOwner(e.partial).id==owner.id &&
        PartialOwnLiftControls::failedOwner(e.partial).generation==owner.generation);
  JS_ClearPendingException(&e.cx);
  CHECK(e.imports.cancelAll(&e.cx) && !e.partial.collectCancelled(&e.cx));
  CHECK(owners[owner.id].attempts==2 && owners[owner.id].refunds==0);
  refuse_id=0; JS_ClearPendingException(&e.cx);
  CHECK(e.imports.cancelAll(&e.cx) && e.partial.collectCancelled(&e.cx));
  CHECK(owners[owner.id].attempts==3 && owners[owner.id].refunds==1 && disposals==0);
  CHECK(e.finish()); return true;
}
bool partial_failed_ack_fences_prepare() {
  Environment e; CHECK(e.begin()); uint32_t still_reserved=0,completed=0;
  CHECK(partial_bind(&e.cx,e.partial,&e.callback));
  CHECK(e.reserve(still_reserved) && e.reserve(completed));
  CHECK(e.partial.prepare(&e.cx,completed,12,partial_get,partial_dispose,1));
  const auto owner=PartialOwnLiftControls::owner(e.partial,completed);
  CHECK(e.imports.cancel(&e.cx,completed)); refuse_id=owner.id;
  CHECK(!e.partial.collect(&e.cx) && owners[owner.id].live);
  const auto admitted=registrations;
  for (unsigned attempt=0;attempt<2;++attempt) {
    JS_ClearPendingException(&e.cx);
    CHECK(!e.partial.prepare(&e.cx,still_reserved,12,partial_get,partial_dispose,1));
    const auto retained=PartialOwnLiftControls::failedOwner(e.partial);
    CHECK(registrations==admitted && retained.id==owner.id && retained.generation==owner.generation &&
          owners[owner.id].live && owners[owner.id].attempts==1);
  }
  refuse_id=0; JS_ClearPendingException(&e.cx); e.partial.cancelAll();
  CHECK(e.imports.cancelAll(&e.cx) && e.partial.collectCancelled(&e.cx));
  CHECK(owners[owner.id].attempts==2 && owners[owner.id].refunds==1 && disposals==0);
  CHECK(e.finish()); return true;
}
bool partial_cancel_reentrant_ack() {
  Environment e; CHECK(e.begin()); uint32_t first=0,second=0;
  CHECK(partial_bind(&e.cx,e.partial,&e.callback));
  CHECK(e.reserve(first) && e.partial.prepare(&e.cx,first,12,partial_get,partial_dispose,1));
  const auto a=PartialOwnLiftControls::owner(e.partial,first).id;
  CHECK(e.reserve(second) && e.partial.prepare(&e.cx,second,12,partial_get,partial_dispose,1));
  const auto b=PartialOwnLiftControls::owner(e.partial,second).id;
  observed_partial=b; observed_partial_id=second; observed_partial_manager=&e.partial;
  watched_sidecar=PartialOwnLiftControls::node(e.partial,second); partial_reentry_cx=&e.cx;
  e.partial.cancelAll(); CHECK(e.imports.cancelAll(&e.cx));
  // Inject a nested call in the host double; this does not claim real-host reentry.
  partial_reenter=true;
  CHECK(!e.partial.collectCancelled(&e.cx) && partial_reentry_refused && partial_destroyed_before_ack);
  CHECK(owners[b].refunds==1 && owners[b].attempts==1 && owners[a].live && owners[a].attempts==0 &&
        PartialOwnLiftControls::hasNode(e.partial,first));
  JS_ClearPendingException(&e.cx);
  CHECK(!e.partial.collectCancelled(&e.cx) && owners[b].attempts==1 && owners[a].attempts==0);
  return true; // A disrupted collection quarantines remaining original owners.
}
bool partial_cancel_quarantine() {
  Environment e; CHECK(e.begin()); uint32_t id=0;
  CHECK(partial_bind(&e.cx,e.partial,&e.callback));
  CHECK(e.reserve(id) && e.partial.prepare(&e.cx,id,12,partial_get,partial_dispose,1));
  const auto sidecar=PartialOwnLiftControls::owner(e.partial,id).id;
  CHECK(e.returned(id)); refuse_disposer=true; e.partial.cancelAll();
  CHECK(!e.imports.cancelAll(&e.cx) && disposals==1 && !e.partial.collectCancelled(&e.cx));
  CHECK(e.imports.hasPending() && PartialOwnLiftControls::hasNode(e.partial,id) &&
        owners[sidecar].live && owners[sidecar].attempts==0);
  refuse_disposer=false; JS_ClearPendingException(&e.cx);
  CHECK(!e.imports.cancelAll(&e.cx) && !e.partial.collectCancelled(&e.cx));
  CHECK(disposals==1 && owners[sidecar].live && owners[sidecar].attempts==0);
  return true; // The uncertain resource and exact owners deliberately remain quarantined.
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
  if (!std::strcmp(name,"import-param-cleanup-queue-fence")) return import_allocation_cleanup_fence(0,false);
  if (!std::strcmp(name,"import-param-cleanup-task-fence")) return import_allocation_cleanup_fence(0,true);
  if (!std::strcmp(name,"import-result-cleanup-queue-fence")) return import_allocation_cleanup_fence(1,false);
  if (!std::strcmp(name,"import-result-cleanup-task-fence")) return import_allocation_cleanup_fence(1,true);
  if (!std::strcmp(name,"import-array-cleanup-queue-fence")) return import_allocation_cleanup_fence(2,false);
  if (!std::strcmp(name,"import-array-cleanup-task-fence")) return import_allocation_cleanup_fence(2,true);
  if (!std::strcmp(name,"import-promise-cleanup-queue-fence")) return import_allocation_cleanup_fence(3,false);
  if (!std::strcmp(name,"import-promise-cleanup-task-fence")) return import_allocation_cleanup_fence(3,true);
  if (!std::strcmp(name,"import-allocation-result-ack-fence")) return import_allocation_ack_fence(0);
  if (!std::strcmp(name,"import-allocation-native-ack-fence")) return import_allocation_ack_fence(1);
  if (!std::strcmp(name,"import-allocation-record-ack-fence")) return import_allocation_ack_fence(2);
  if (!std::strcmp(name,"import-dispatched-cleanup-fence")) return import_dispatched_cleanup_fence(false);
  if (!std::strcmp(name,"import-dispatched-cancel-fence")) return import_dispatched_cleanup_fence(true);
  if (!std::strcmp(name,"import-partial-rollback-native")) return import_partial_rollback_retry(0);
  if (!std::strcmp(name,"import-partial-rollback-queue")) return import_partial_rollback_retry(1);
  if (!std::strcmp(name,"import-partial-rollback-task")) return import_partial_rollback_retry(2);
  if (!std::strcmp(name,"import-partial-admission-physical-order")) return import_partial_admission_physical_order();
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
  if (!std::strcmp(name,"partial-cancel-undispatched")) return partial_cancel_undispatched();
  if (!std::strcmp(name,"borrow-unallocated-cleanup")) return borrow_unallocated_retry(false);
  if (!std::strcmp(name,"borrow-unallocated-ack-retry")) return borrow_unallocated_retry(true);
  if (!std::strcmp(name,"borrow-partial-setup-quarantine")) return borrow_partial_setup_quarantine();
  if (!std::strcmp(name,"borrow-published-release")) return borrow_published_release();
  if (!std::strcmp(name,"partial-cancel-retry")) return partial_cancel_retry();
  if (!std::strcmp(name,"partial-cancel-pending")) return partial_cancel_pending();
  if (!std::strcmp(name,"partial-cancel-returned")) return partial_cancel_returned();
  if (!std::strcmp(name,"partial-regular-ack-retry")) return partial_regular_ack_retry();
  if (!std::strcmp(name,"partial-failed-ack-fences-prepare")) return partial_failed_ack_fences_prepare();
  if (!std::strcmp(name,"partial-cancel-reentrant-ack")) return partial_cancel_reentrant_ack();
  if (!std::strcmp(name,"partial-cancel-quarantine")) return partial_cancel_quarantine();
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
