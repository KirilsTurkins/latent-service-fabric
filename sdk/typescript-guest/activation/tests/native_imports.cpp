// Real selected-engine Promise/timer controls with a finite diagnostic broker.
// The imported signatures are the exact generated activation/P3 ABI. This
// fixture does not qualify a real LSF host or signed Component Model guest.
#include "../native_timers.h"
#include "../native_imports.h"
#include "../promise_accounting.h"
#include "../promise_hooks.h"
#include "../reaction_records.h"
#include "js/CompilationAndEvaluation.h"
#include "js/Conversions.h"
#include "js/GCAPI.h"
#include "js/Initialization.h"
#include "js/Prefs.h"
#include "js/SourceText.h"
#include "jsfriendapi.h"
#include <array>
#include <cstdio>
#include <cstring>
#ifdef LSF_TYPESCRIPT_BORROW_CONTROLS
// Owning recipe supplies the exact pinned pre-feature header, unmodified.
#define Imports BorrowBaselineImports
#include "borrow-baseline-native-imports.h"
#undef Imports
namespace lsf::typescript::activation {
struct ImportBorrowControls {
  static const void* record(Imports& imports,uint32_t id) {return imports.find(id);}
  static Token recordOwner(Imports& imports,uint32_t id) {return imports.find(id)->record_owner.token;}
  static size_t recordBytes() {return sizeof(Imports::Record);}
  static ImportBorrowObserver* observer(JSContext* cx,Imports& imports,uint32_t id) {
    auto* item=imports.find(id);if(!item)return nullptr;
    std::unique_ptr<ImportBorrowObserver>* link=nullptr;
    return imports.observerLink(cx,id,item->record_owner.token,link)?link->get():nullptr;
  }
  static bool refuseCycle(JSContext* cx,Imports& imports,uint32_t id) {
    auto* item=observer(cx,imports,id);
    if(!item || imports.observer_count_!=1 || item->following)return false;
    item->following.reset(item); // deliberate fixture-only invariant corruption
    std::unique_ptr<ImportBorrowObserver>* ignored=nullptr;
    const bool refused=!imports.observerLink(cx,0,Token{},ignored);
    (void)item->following.release(); // restore unique ownership before teardown
    return refused;
  }
};
}
#endif

using namespace lsf::typescript::activation;
namespace {
struct Owner { bool live = false; uint8_t kind = 0; bool parked = false; bool managed_promise = false; };
struct Timer { bool live = false; uint64_t period = 0; };
struct Wait {
  bool live = false, joined = false, cancel_requested = false;
  jobs_subtask_state_t state = JOBS_SUBTASK_STARTED;
  uint64_t timer = 0;
  latent_runtime_activation_result_u64_error_t* result = nullptr;
  uint32_t* imported_result = nullptr;
};
std::array<Owner, 256> owners;
std::array<Timer, 256> timer_records;
std::array<Wait, 64> waits;
std::array<unsigned, 8> counts{};
std::array<unsigned, 8> limits{16, 2, 2, 16, 8, 8, 8, 64};
uint64_t next_owner = 1;
uint32_t next_wait = 1;
bool closed = false, effects = true, set_live = false, immediate_return = false;
bool compiler_phase = false;
bool block_import = false;
unsigned imported_starts = 0, imported_lifts = 0;
bool defer_cancel = false, refuse_stop = false, refuse_native_ack = false, refuse_task_ack = false;
unsigned starts = 0, stops = 0, drops = 0, set_drops = 0, waits_entered = 0;
unsigned callback_entries = 0, native_admissions = 0, native_acknowledgements = 0;
unsigned host_calls = 0;
unsigned cancel_requests = 0;
bool host_in_gc = false, in_gc = false;
uint64_t observed_period = 0;
#ifdef LSF_TYPESCRIPT_BORROW_CONTROLS
bool admitting_promise=false,expected_quarantine=false,capturing_observer_owner=false;
std::array<bool,256> expected_retained{};
uint64_t refuse_owner=0,record_owner_id=0,result_owner_id=0,lowering_owner_id=0,observer_owner_id=0;
unsigned exact_refusals=0;
const void* record_address=nullptr;
const void* observer_address=nullptr;
bool record_destroyed=false,observer_destroyed=false,drop_order_valid=true;
void note_deleted(void* pointer) {
  if(pointer && pointer==record_address)record_destroyed=true;
  if(pointer && pointer==observer_address)observer_destroyed=true;
}
void note_settle(uint64_t id) {
  if(id && (id==record_owner_id || id==result_owner_id || id==lowering_owner_id))
    drop_order_valid=drop_order_valid && record_destroyed;
  if(id && id==observer_owner_id)
    drop_order_valid=drop_order_valid && record_destroyed && observer_destroyed;
}
#endif

bool valid(const latent_runtime_activation_token_t* token) {
  return token && token->generation == 1 && token->id < next_owner && owners[token->id].live;
}
bool failed(latent_runtime_activation_error_t* error, uint8_t value) {
  *error = value; return false;
}
void note_host() { ++host_calls; if (in_gc) host_in_gc = true; }
bool allowed(JSContext*) { return effects; }
bool snapshot_allowed(JSContext*) { return compiler_phase && !effects; }
BrokerPromiseAccounting::Phase phase(JSContext*) {
  return effects ? BrokerPromiseAccounting::Phase::Activation
                 : BrokerPromiseAccounting::Phase::CompilerSnapshot;
}
void ready(jobs_event_t* event) {
  *event = {};
  for (uint32_t id = 1; id < next_wait; ++id) {
    auto& wait = waits[id];
    if (!wait.live || !wait.joined || wait.state == JOBS_SUBTASK_RETURNED ||
        wait.state == JOBS_SUBTASK_STARTED_CANCELLED ||
        wait.state == JOBS_SUBTASK_RETURNED_CANCELLED) continue;
    if (wait.imported_result && block_import && !wait.cancel_requested) continue;
    if (wait.cancel_requested) {
      wait.state = JOBS_SUBTASK_RETURNED_CANCELLED;
      // A cancelled result buffer deliberately remains unreadable.
    } else {
      wait.state = JOBS_SUBTASK_RETURNED;
      if (wait.imported_result) *wait.imported_result = 42;
      else {
        wait.result->is_err = false;
        wait.result->val.ok = timer_records[wait.timer].period ? 3 : 0;
      }
    }
    *event = {JOBS_EVENT_SUBTASK, id, static_cast<uint32_t>(wait.state)};
    return;
  }
}
}

#ifdef LSF_TYPESCRIPT_BORROW_CONTROLS
// Linker-only observation AFTER all members, including persistent roots, have
// destructed. Forward to the real selected allocator; never substitute free.
// The diagnostic compiles with -fno-sized-deallocation and --wrap=_ZdlPv.
extern "C" void __real__ZdlPv(void*) noexcept;
extern "C" void __wrap__ZdlPv(void* pointer) noexcept {
  note_deleted(pointer);
  __real__ZdlPv(pointer);
}
#endif

extern "C" {
bool latent_runtime_activation_register(latent_runtime_activation_owner_kind_t kind,
    latent_runtime_activation_token_t* parent, latent_runtime_activation_token_t* output,
    latent_runtime_activation_error_t* error) {
  note_host();
  if (!effects || (closed && !valid(parent)))
    return failed(error, LATENT_RUNTIME_ACTIVATION_ERROR_CANCELLED);
  if (kind >= counts.size() || counts[kind] >= limits[kind] || next_owner >= owners.size())
    return failed(error, LATENT_RUNTIME_ACTIVATION_ERROR_RESOURCE_EXHAUSTED);
  const auto id = next_owner++;
  owners[id] = {true, kind, false}; ++counts[kind];
#ifdef LSF_TYPESCRIPT_BORROW_CONTROLS
  owners[id].managed_promise=admitting_promise;
  if(capturing_observer_owner && !admitting_promise && kind==LATENT_RUNTIME_ACTIVATION_OWNER_KIND_NATIVE) {
    if(observer_owner_id)__builtin_trap();
    observer_owner_id=id;
    expected_retained[id]=true; // exact admitted node token, before Promise admission can fail
  }
#endif
  if (kind == LATENT_RUNTIME_ACTIVATION_OWNER_KIND_NATIVE) ++native_admissions;
  *output = {1, id}; return true;
}
bool latent_runtime_activation_park(latent_runtime_activation_token_t* owner,
                                   latent_runtime_activation_error_t* error) {
  note_host();
  if (!valid(owner)) return failed(error, LATENT_RUNTIME_ACTIVATION_ERROR_INVALID_TOKEN);
  owners[owner->id].parked = true; return true;
}
bool latent_runtime_activation_wake(latent_runtime_activation_token_t* owner,
                                   latent_runtime_activation_error_t* error) {
  note_host();
  if (!valid(owner)) return failed(error, LATENT_RUNTIME_ACTIVATION_ERROR_INVALID_TOKEN);
  owners[owner->id].parked = false; ++callback_entries; return true;
}
bool latent_runtime_activation_settle(latent_runtime_activation_token_t* owner,
                                     latent_runtime_activation_error_t* error) {
  note_host();
  if (!valid(owner)) return failed(error, LATENT_RUNTIME_ACTIVATION_ERROR_INVALID_TOKEN);
#ifdef LSF_TYPESCRIPT_BORROW_CONTROLS
  note_settle(owner->id);
  if(owner->id==refuse_owner) {
    ++exact_refusals;
    return failed(error,LATENT_RUNTIME_ACTIVATION_ERROR_UNAVAILABLE);
  }
#endif
  auto& actual = owners[owner->id];
  if ((actual.kind == LATENT_RUNTIME_ACTIVATION_OWNER_KIND_NATIVE && refuse_native_ack) ||
      (actual.kind == LATENT_RUNTIME_ACTIVATION_OWNER_KIND_TASK && refuse_task_ack))
    return failed(error, LATENT_RUNTIME_ACTIVATION_ERROR_UNAVAILABLE);
  --counts[actual.kind]; actual.live = false;
  if (actual.kind == LATENT_RUNTIME_ACTIVATION_OWNER_KIND_NATIVE) ++native_acknowledgements;
  return true;
}
bool latent_runtime_activation_close(latent_runtime_activation_error_t*) {
  note_host(); closed = true; return true;
}
bool latent_runtime_activation_timer_start(uint64_t, uint64_t* period,
    latent_runtime_activation_token_t* parent, latent_runtime_activation_token_t* output,
    latent_runtime_activation_error_t* error) {
  note_host();
  if (!latent_runtime_activation_register(LATENT_RUNTIME_ACTIVATION_OWNER_KIND_TIMER,
                                          parent, output, error)) return false;
  timer_records[output->id] = {true, period ? *period : 0};
  observed_period = period ? *period : 0; ++starts; return true;
}
jobs_subtask_status_t latent_runtime_activation_timer_next(
    latent_runtime_activation_token_t timer, latent_runtime_activation_result_u64_error_t* result) {
  note_host();
  if (!valid(&timer) || !timer_records[timer.id].live || next_wait >= waits.size()) return 15;
  for (const auto& wait : waits)
    if (wait.live && wait.timer == timer.id) return 15;
  if (immediate_return) {
    result->is_err = false; result->val.ok = 0;
    return JOBS_SUBTASK_RETURNED; // no original subtask handle exists
  }
  const auto id = next_wait++;
  waits[id] = {true, false, false, JOBS_SUBTASK_STARTED, timer.id, result};
  result->is_err = true; result->val.err = LATENT_RUNTIME_ACTIVATION_ERROR_UNAVAILABLE;
  ++counts[LATENT_RUNTIME_ACTIVATION_OWNER_KIND_WAIT];
  return (id << 4) | JOBS_SUBTASK_STARTED;
}
bool latent_runtime_activation_timer_stop(latent_runtime_activation_token_t* timer,
                                         latent_runtime_activation_error_t* error) {
  note_host();
  if (refuse_stop) return failed(error, LATENT_RUNTIME_ACTIVATION_ERROR_UNAVAILABLE);
  if (!valid(timer) || !timer_records[timer->id].live)
    return failed(error, LATENT_RUNTIME_ACTIVATION_ERROR_INVALID_TOKEN);
  timer_records[timer->id].live = false; ++stops;
  return latent_runtime_activation_settle(timer, error);
}
jobs_subtask_status_t jobs_subtask_cancel(jobs_subtask_t handle) {
  note_host();
  ++cancel_requests;
  if (!handle || handle >= next_wait || !waits[handle].live) return 15;
  auto& wait = waits[handle]; wait.cancel_requested = true;
  if (wait.state != JOBS_SUBTASK_RETURNED && !defer_cancel)
    wait.state = JOBS_SUBTASK_STARTED_CANCELLED;
  return wait.state; // original plain cancellation state, no new packed handle
}
uint32_t lsf_async_subtask_cancel(uint32_t handle) {
  const auto state = jobs_subtask_cancel(handle);
  return state == JOBS_SUBTASK_STARTING || state == JOBS_SUBTASK_STARTED
      ? SubtaskCancellationBlocked : state;
}
void jobs_subtask_drop(jobs_subtask_t handle) {
  note_host();
  auto& wait = waits[handle];
  if (!wait.live || wait.joined ||
      (wait.state != JOBS_SUBTASK_RETURNED && wait.state != JOBS_SUBTASK_STARTED_CANCELLED &&
       wait.state != JOBS_SUBTASK_RETURNED_CANCELLED)) __builtin_trap();
  wait.live = false; wait.result = nullptr; ++drops;
  --counts[LATENT_RUNTIME_ACTIVATION_OWNER_KIND_WAIT];
}
jobs_waitable_set_t jobs_waitable_set_new() {
  note_host(); if (set_live) __builtin_trap(); set_live = true; return 1;
}
void jobs_waitable_join(uint32_t handle, jobs_waitable_set_t set) {
  note_host();
  if (!handle || handle >= next_wait || !waits[handle].live || (set && !set_live))
    __builtin_trap();
  waits[handle].joined = set != 0;
}
void jobs_waitable_set_drop(jobs_waitable_set_t set) {
  note_host();
  if (set != 1 || !set_live) __builtin_trap();
  for (const auto& wait : waits) if (wait.live && wait.joined) __builtin_trap();
  set_live = false; ++set_drops;
}
void jobs_waitable_set_wait(jobs_waitable_set_t set, jobs_event_t* event) {
  note_host(); if (set != 1 || !set_live) __builtin_trap();
  ++waits_entered; ready(event);
}
void jobs_waitable_set_poll(jobs_waitable_set_t set, jobs_event_t* event) {
  note_host(); if (set != 1 || !set_live) __builtin_trap(); *event = {};
}
}

static BrokerAccounting* job_broker;
static PromiseRecords* promise_records;
static ReactionRecords* reaction_records;
static Timers* timer_runtime;
static Imports* import_runtime;
static bool imported_global(JSContext* cx,unsigned argc,JS::Value* vp) {
  auto args=JS::CallArgsFromVp(argc,vp);uint32_t id=0;
  if(!import_runtime->reserve(cx,4,0,ImportRawResult::I32,JS::HandleValueArray::empty(),id))return false;
  auto* result=static_cast<uint32_t*>(import_runtime->resultBuffer(id));
  if(!result || !import_runtime->beginLowering(cx,id))return false;
  const auto wait_id=next_wait++;
  if(wait_id>=waits.size())return false;
  waits[wait_id]={true,false,false,JOBS_SUBTASK_STARTED,0,nullptr,result};
  ++counts[LATENT_RUNTIME_ACTIVATION_OWNER_KIND_WAIT];++imported_starts;
  JS::RootedObject promise(cx);
  if(!import_runtime->started(cx,id,(wait_id<<4)|JOBS_SUBTASK_STARTED,&promise))return false;
  args.rval().setObject(*promise);return true;
}
static bool lift_imported(JSContext* cx,unsigned argc,JS::Value* vp) {
  auto args=JS::CallArgsFromVp(argc,vp);
  if(argc!=1 || !args[0].isInt32())return false;
  const auto id=static_cast<uint32_t>(args[0].toInt32());
  if(!import_runtime->liftValue(cx,id,args.rval()))return false;
  ++imported_lifts;
  return import_runtime->liftCompleted(cx,id);
}
static bool release_imported(JSContext*,unsigned argc,JS::Value* vp) {
  auto args=JS::CallArgsFromVp(argc,vp);block_import=false;args.rval().setUndefined();return true;
}
static bool shared_drain(JSContext* cx,JobQueue& queue,Timers& timers,Imports& imports,ReadinessSet& readiness) {
  for(unsigned turn=0;turn!=64;++turn) {
    js::RunJobs(cx);
    if(queue.isDrainingStopped() || JS_IsExceptionPending(cx))return false;
    if(!imports.turn(cx) || !timers.turn(cx,false,false))return false;
    if(!queue.empty() || timers.callbackDispatched() || imports.hasReady())continue;
    if(readiness.hasJoined()) {if(!readiness.dispatch(cx,true))return false;continue;}
    if(imports.hasPending() || timers.hasPendingRecords())return false;
    return readiness.retire(cx) && queue.empty();
  }
  return false;
}
static bool before_promise(JSContext* cx, void** output) {
#ifdef LSF_TYPESCRIPT_BORROW_CONTROLS
  const bool previous=admitting_promise;admitting_promise=true;
#endif
  const bool accepted=promise_records->checkpoint(cx) && reaction_records->checkpoint(cx) &&
         promise_records->beforeAllocate(cx, output);
#ifdef LSF_TYPESCRIPT_BORROW_CONTROLS
  admitting_promise=previous;
#endif
  return accepted;
}
static bool before_reaction(JSContext* cx, void** output) {
  return promise_records->checkpoint(cx) && reaction_records->checkpoint(cx) &&
         reaction_records->beforeAllocate(cx, output);
}
static void settled_promise(JSContext* cx, JSObject* object) { promise_records->settled(cx, object); }
static void* reaction_record(JSContext* cx, JSObject* object) { return reaction_records->record(cx, object); }
static void weak_sweep(JSTracer* tracer, void*) {
  promise_records->sweep(tracer); reaction_records->sweep(tracer);
}
static void collection_end(JS::GCContext*, JSFinalizeStatus status, void*) {
  if (status != JSFINALIZE_COLLECTION_END) return;
  promise_records->collectionCompleted(); reaction_records->collectionCompleted();
}
static bool transfer(JSContext* cx, JS::HandleObject job, JobOwners& owners, bool& moved) {
  void* record = nullptr;
  if (!JS::ActivationReactionRecordForJob(cx, job, &record)) return false;
  if (!record) return true;
  moved = reaction_records->transfer(cx, record, owners); return moved;
}
static bool timer_global(JSContext* cx, unsigned argc, JS::Value* vp, bool repeat) {
  const auto args = JS::CallArgsFromVp(argc, vp);
  if (argc == 0 || !args[0].isObject() || !JS::IsCallable(&args[0].toObject())) return false;
  JS::RootedObject function(cx, &args[0].toObject());
  int32_t delay = 0, id = 0;
  if (argc > 1 && !JS::ToInt32(cx, args[1], &delay)) return false;
  const auto values = argc > 2
      ? JS::HandleValueArray::subarray(JS::HandleValueArray(args), 2, argc - 2)
      : JS::HandleValueArray::empty();
  if (!timer_runtime->start(cx, function, values, delay, repeat, &id)) return false;
  args.rval().setInt32(id); return true;
}
static bool timeout_global(JSContext* cx, unsigned argc, JS::Value* vp) {
  return timer_global(cx, argc, vp, false);
}
static bool interval_global(JSContext* cx, unsigned argc, JS::Value* vp) {
  return timer_global(cx, argc, vp, true);
}
static bool clear_global(JSContext* cx, unsigned argc, JS::Value* vp) {
  const auto args = JS::CallArgsFromVp(argc, vp);
  int32_t id = 0;
  if (argc && !JS::ToInt32(cx, args[0], &id)) return false;
  if (!timer_runtime->clear(cx, id)) return false;
  args.rval().setUndefined(); return true;
}
static bool root_done(JSContext* cx, unsigned argc, JS::Value* vp) {
  const auto args = JS::CallArgsFromVp(argc, vp);
  if (!job_broker->settleRoot(cx)) return false;
  args.rval().setUndefined(); return true;
}
static bool evaluate(JSContext* cx, const char* code, JS::MutableHandleValue output) {
  JS::CompileOptions options(cx); options.setFileAndLine("native-selected-timer-controls.js", 1);
  JS::SourceText<mozilla::Utf8Unit> text;
  return text.init(cx, code, std::strlen(code), JS::SourceOwnership::Borrowed) &&
         JS::Evaluate(cx, options, text, output);
}
static bool expect(JSContext* cx, const char* code) {
  JS::RootedValue value(cx);
  return evaluate(cx, code, &value) && value.isBoolean() && value.toBoolean();
}
static bool drain(JSContext* cx, JobQueue& queue, Timers& timers) {
  // This is the native fixture pump, never an application manual drain API.
  for (unsigned turn = 0; turn != 64; ++turn) {
    js::RunJobs(cx);
    if (queue.isDrainingStopped() || JS_IsExceptionPending(cx)) return false;
    if (!timers.hasPending()) return queue.empty();
    if (!queue.empty() || !timers.turn(cx, true)) return false;
  }
  return false; // finite diagnostic bound; no changed real activation deadline
}
static void collect(JSContext* cx) { in_gc = true; JS_GC(cx); in_gc = false; }

#ifdef LSF_TYPESCRIPT_BORROW_CONTROLS
static bool borrow_refusal(JSContext* cx,BrokerAccounting& jobs,BrokerPromiseAccounting& native,
                           ReadinessSet& readiness,const char* selected) {
  const bool promise_denied=!std::strcmp(selected,"borrow-refusal-observer-Promise-admission");
  const bool cycle=!std::strcmp(selected,"borrow-refusal-bounded-cycle");
  const bool work=!std::strcmp(selected,"borrow-refusal-original-work-ack");
  Token root;
  if(!jobs.currentContinuation(root))return false;
  bool passed=false;
  {
    // This manager is physically destroyed before JSContext destruction, while
    // the exact refused broker tokens remain paid. No fake refund/reset follows.
    Imports held(jobs,native,readiness);
    uint32_t id=0;JS::RootedObject handle(cx),original(cx),released(cx);
    const auto first=next_owner;
    if(!held.reserve(cx,4,4,ImportRawResult::I32,JS::HandleValueArray::empty(),id))return false;
    record_address=ImportBorrowControls::record(held,id);
    record_owner_id=ImportBorrowControls::recordOwner(held,id).id;
    uint64_t work_owner=0,queued_owner=0;
    for(uint64_t owner=first;owner<next_owner;++owner) {
      if(owners[owner].managed_promise)continue;
      if(owners[owner].kind==LATENT_RUNTIME_ACTIVATION_OWNER_KIND_RESULT) {
        if(result_owner_id)return false;
        result_owner_id=owner;
      }
      if(owners[owner].kind==LATENT_RUNTIME_ACTIVATION_OWNER_KIND_TASK) {
        if(work_owner)return false;
        work_owner=owner;
      }
      if(owners[owner].kind==LATENT_RUNTIME_ACTIVATION_OWNER_KIND_QUEUED_WORK) {
        if(queued_owner)return false;
        queued_owner=owner;
      }
      if(owners[owner].kind==LATENT_RUNTIME_ACTIVATION_OWNER_KIND_NATIVE &&
         owner!=record_owner_id) {
        if(lowering_owner_id)return false;
        lowering_owner_id=owner;
      }
    }
    if(!record_owner_id || !result_owner_id || !lowering_owner_id || !work_owner || !queued_owner)return false;
    const bool result_ack=!std::strcmp(selected,"borrow-refusal-original-result-ack");
    const bool native_ack=!std::strcmp(selected,"borrow-refusal-original-native-ack");
    const bool record_ack=!std::strcmp(selected,"borrow-refusal-original-record-ack");
    const bool observer_ack=!std::strcmp(selected,"borrow-refusal-observer-owner-ack");
    if(!(promise_denied || cycle || work || result_ack || native_ack || record_ack || observer_ack))return false;
    // Derive expectations from known original tokens and the unchanged release
    // sequence BEFORE inducing refusal. Never bless the observed post-failure
    // state: both premature refunds and unexpected retained owners must fail.
    expected_retained.fill(false);
    if(work)expected_retained[work_owner]=true;
    if(promise_denied || cycle || work || result_ack)expected_retained[result_owner_id]=true;
    if(promise_denied || cycle || work || result_ack || native_ack)expected_retained[lowering_owner_id]=true;
    if(!observer_ack)expected_retained[record_owner_id]=true;
    // The exact accepted queued token must retire on started()/park or on the
    // original Reserved-import finally, including either pre-dispatch refusal.
    expected_retained[queued_owner]=false;
    const auto admitted=native_admissions;
    if(promise_denied)limits[LATENT_RUNTIME_ACTIVATION_OWNER_KIND_NATIVE]=
      counts[LATENT_RUNTIME_ACTIVATION_OWNER_KIND_NATIVE]+1; // node fits; Promise does not
    // Capture the exact observer owner as the fixture broker admits it, before
    // watchBorrow allocates the node/root or attempts the managed Promise.
    capturing_observer_owner=true;
    const bool watched=held.watchBorrow(cx,id,&handle);
    capturing_observer_owner=false;
    limits[LATENT_RUNTIME_ACTIVATION_OWNER_KIND_NATIVE]=8;
    auto* observer=ImportBorrowControls::observer(cx,held,id);
    if(!observer || !observer_owner_id || observer->allocation_owner.token.id!=observer_owner_id)return false;
    observer_address=observer;
    if(promise_denied) {
      if(watched || handle || !JS_IsExceptionPending(cx) || native_admissions!=admitted+1 ||
         !observer->quarantined || observer->handle)return false;
      // The generated finally still runs. Quarantine prevents a partial
      // observer/Promise admission failure from becoming a release proof.
      if(held.liftCompleted(cx,id))return false;
    } else {
      if(!watched || !held.observeBorrow(cx,handle,false,&released))return false;
      if(cycle) {
        if(!ImportBorrowControls::refuseCycle(cx,held,id) || !JS_IsExceptionPending(cx) ||
           held.liftCompleted(cx,id))return false;
      } else {
        auto* result=static_cast<uint32_t*>(held.resultBuffer(id));
        if(!result || !held.parameterBuffer(id) || !held.beginLowering(cx,id))return false;
        const auto wait_id=next_wait++;
        if(wait_id>=waits.size())return false;
        waits[wait_id]={true,false,false,JOBS_SUBTASK_STARTED,0,nullptr,result};
        ++counts[LATENT_RUNTIME_ACTIVATION_OWNER_KIND_WAIT];
        if(!held.started(cx,id,(wait_id<<4)|JOBS_SUBTASK_STARTED,&original))return false;
        if(work)refuse_owner=work_owner;
        else if(result_ack)refuse_owner=result_owner_id;
        else if(native_ack)refuse_owner=lowering_owner_id;
        else if(record_ack)refuse_owner=record_owner_id;
        else if(observer_ack)refuse_owner=observer_owner_id;
        else return false;
        if(held.observeBorrow(cx,handle,true,&released) || !JS_IsExceptionPending(cx) ||
           JS::GetPromiseState(original)!=JS::PromiseState::Rejected || exact_refusals!=1 ||
           !owners[refuse_owner].live || drops!=1 || cancel_requests!=1)return false;
        if(work && record_destroyed)return false;
        if(!work && !record_destroyed)return false;
        if((refuse_owner==observer_owner_id)!=observer_destroyed)return false;
      }
      if(JS::GetPromiseState(released)!=JS::PromiseState::Pending)return false;
    }
    const auto calls=host_calls;
    JS_ClearPendingException(cx);
    if(held.turn(cx) || !JS_IsExceptionPending(cx) || host_calls!=calls || !held.hasPending())return false;
    JS_ClearPendingException(cx);
    refuse_owner=0;
    if(!readiness.retire(cx))return false;
    for(uint64_t owner=1;owner<next_owner;++owner)
      if((owners[owner].live && !owners[owner].managed_promise && owner!=root.id)!=expected_retained[owner])return false;
    expected_quarantine=true;
    passed=drop_order_valid;
  }
  // The original record and observer have now actually destructed. They still
  // cannot refund any of the failed/unknown ownership captured above.
  for(uint64_t owner=1;owner<next_owner;++owner)
    if((owners[owner].live && !owners[owner].managed_promise && owner!=root.id)!=expected_retained[owner])passed=false;
  return passed && record_destroyed && observer_destroyed;
}
#endif

int main(int argc, char** argv) {
  if (argc != 2) return 2;
  JS::Prefs::set_use_js_microtask_queue(false);
  if (!JS_Init()) return 3;
  JSContext* cx = JS_NewContext(32*1024*1024);
  if (!cx) return 4;
  BrokerAccounting jobs(allowed, snapshot_allowed);
  BrokerPromiseAccounting native(phase, jobs);
  PromiseRecords promises(native);
  ReactionRecords reactions(native, jobs);
  JobQueue queue(jobs, transfer);
  ReadinessSet readiness(native);
  Timers timers(jobs, native,readiness);
  Imports imports(jobs,native,readiness);
  import_runtime=&imports;
  job_broker = &jobs; promise_records = &promises;
  reaction_records = &reactions; timer_runtime = &timers;
  int status = 1;
  {
    if (!js::UseInternalJobQueues(cx) || !JS::InitSelfHostedCode(cx)) return 5;
    JS::SetJobQueue(cx, &queue);
    static const JSClass global_class = {"LSFNativeTimerControls", JSCLASS_GLOBAL_FLAGS,
                                        &JS::DefaultGlobalClassOps};
    JS::RealmOptions realm_options;
    JS::RootedObject global(cx, JS_NewGlobalObject(cx, &global_class, nullptr,
                                                 JS::FireOnNewGlobalHook, realm_options));
    if (!global) return 6;
    JSAutoRealm realm(cx, global);
    if (!JS::InitRealmStandardClasses(cx)) return 7;
    static const JS::ActivationPromiseHooks hooks{
        before_promise, PromiseRecords::allocationFailed, PromiseRecords::created, settled_promise,
        before_reaction, ReactionRecords::allocationFailed, ReactionRecords::created, reaction_record,
        before_reaction, ReactionRecords::allocationFailed, ReactionRecords::created, reaction_record};
    if (!JS_AddWeakPointerZonesCallback(cx, weak_sweep, nullptr)) return 8;
    if (!JS_AddFinalizeCallback(cx, collection_end, nullptr) ||
        !JS::SetActivationPromiseHooks(cx, &hooks)) return 8;
    if (!JS_DefineFunction(cx, global, "setTimeout", timeout_global, 1, 0) ||
        !JS_DefineFunction(cx, global, "setInterval", interval_global, 1, 0) ||
        !JS_DefineFunction(cx, global, "clearTimeout", clear_global, 0, 0) ||
        !JS_DefineFunction(cx, global, "clearInterval", clear_global, 0, 0) ||
        !JS_DefineFunction(cx, global, "rootDone", root_done, 0, 0) ||
        !JS_DefineFunction(cx, global, "ordinaryImported", imported_global, 0, 0) ||
        !JS_DefineFunction(cx, global, "liftImported", lift_imported, 1, 0) ||
        !JS_DefineFunction(cx, global, "releaseImported", release_imported, 0, 0)) return 8;
    if (!jobs.beginRoot(cx)) return 9;
    JS::RootedValue output(cx);
    const char* selected = argv[1];
#ifdef LSF_TYPESCRIPT_BORROW_CONTROLS
    if(!std::strncmp(selected,"borrow-refusal-",15)) {
      status=borrow_refusal(cx,jobs,native,readiness,selected)?0:1;
    } else
#endif
    if (!std::strcmp(selected,"borrow-observer-blocked-cancel-awaits-actual-drop")) {
      // Real SpiderMonkey Promises/accounting; canonical intrinsics below are
      // explicit fixture doubles. Signed Component Model evidence is separate.
      uint32_t id=0;
      JS::RootedObject handle(cx),again(cx),original(cx),released(cx),repeated(cx);
      if(!imports.reserve(cx,4,0,ImportRawResult::I32,JS::HandleValueArray::empty(),id))return 10;
      const auto admitted=native_admissions;
      if(!imports.watchBorrow(cx,id,&handle))return 10;
#ifdef LSF_TYPESCRIPT_BORROW_CONTROLS
      record_address=ImportBorrowControls::record(imports,id);
      record_owner_id=ImportBorrowControls::recordOwner(imports,id).id;
      auto* observer=ImportBorrowControls::observer(cx,imports,id);
      if(!observer)return 10;
      observer_address=observer;observer_owner_id=observer->allocation_owner.token.id;
#endif
      const auto observed_admissions=native_admissions;
      if(!imports.watchBorrow(cx,id,&again) || again.get()!=handle.get() ||
         native_admissions!=observed_admissions || observed_admissions<admitted+2)return 10;
      auto* result=static_cast<uint32_t*>(imports.resultBuffer(id));
      if(!result || !imports.beginLowering(cx,id))return 10;
      const auto wait_id=next_wait++;
      waits[wait_id]={true,false,false,JOBS_SUBTASK_STARTED,0,nullptr,result};
      ++counts[LATENT_RUNTIME_ACTIVATION_OWNER_KIND_WAIT];
      if(!imports.started(cx,id,(wait_id<<4)|JOBS_SUBTASK_STARTED,&original) ||
         !imports.observeBorrow(cx,handle,false,&released))return 10;
      defer_cancel=true;
      if(!imports.observeBorrow(cx,handle,true,&repeated) || repeated.get()!=released.get() ||
         !imports.observeBorrow(cx,handle,true,&repeated) ||
         !imports.liftCompleted(cx,id))return 10; // original generated finally
      const bool held=JS::GetPromiseState(original)==JS::PromiseState::Rejected &&
        JS::GetPromiseState(released)==JS::PromiseState::Pending &&
        cancel_requests==1 && drops==0 && waits[wait_id].live && waits[wait_id].imported_result==result &&
        counts[LATENT_RUNTIME_ACTIVATION_OWNER_KIND_RESULT]==1 && imports.hasPending();
      if(!readiness.dispatch(cx,true) || !imports.turn(cx))return 10;
      status=held && drops==1 && cancel_requests==1 && !imports.hasPending() &&
        JS::GetPromiseState(released)==JS::PromiseState::Fulfilled &&
        imports.observeBorrow(cx,handle,true,&repeated) && repeated.get()==released.get() && cancel_requests==1 ? 0:1;
      defer_cancel=false;
    } else if (!std::strcmp(selected,"borrow-observer-rejects-foreign-and-unregistered-handles")) {
      uint32_t id=0;
      JS::RootedObject handle(cx),promise(cx),plain(cx,JS_NewPlainObject(cx));
      if(!plain || !imports.reserve(cx,0,0,ImportRawResult::None,JS::HandleValueArray::empty(),id) ||
         !imports.watchBorrow(cx,id,&handle))return 10;
      bool refused=!imports.observeBorrow(cx,plain,true,&promise) && JS_IsExceptionPending(cx);
      JS_ClearPendingException(cx);
      Imports foreign(jobs,native,readiness);
      refused=refused && !foreign.observeBorrow(cx,handle,true,&promise) && JS_IsExceptionPending(cx);
      JS_ClearPendingException(cx);
      NativeOwner control_owner;
      if(!native.beforeAllocate(cx,control_owner))return 10;
      {
        ImportBorrowObserver forged(cx,id,Token{jobs.generation(),999});
        if(!forged.initialize(cx,&imports,id,Token{jobs.generation(),999}))return 10;
        refused=refused && !imports.observeBorrow(cx,forged.handle,true,&promise) && JS_IsExceptionPending(cx);
        JS_ClearPendingException(cx);
      }
      {
        // A branded but released handle from another epoch must fail BEFORE
        // the released fast path, even with this exact manager and context.
        ImportBorrowObserver stale(cx,id,Token{jobs.generation()+1,999});
        if(!stale.initialize(cx,&imports,id,Token{jobs.generation()+1,999}) ||
           !ImportBorrowObserver::acknowledge(cx,stale.handle))return 10;
        refused=refused && !imports.observeBorrow(cx,stale.handle,false,&promise) && JS_IsExceptionPending(cx);
        JS_ClearPendingException(cx);
      }
      if(!native.acknowledgeRetirement(cx,control_owner))return 10;
      status=refused && cancel_requests==0 && imports.cancel(cx,id) ? 0:1;
    } else if (!std::strcmp(selected,"borrow-observer-native-denial-precedes-node-and-Promise")) {
      uint32_t id=0;JS::RootedObject handle(cx);
      if(!imports.reserve(cx,0,0,ImportRawResult::None,JS::HandleValueArray::empty(),id))return 10;
      const auto admitted=native_admissions;
      limits[LATENT_RUNTIME_ACTIVATION_OWNER_KIND_NATIVE]=counts[LATENT_RUNTIME_ACTIVATION_OWNER_KIND_NATIVE];
      const bool refused=!imports.watchBorrow(cx,id,&handle) && JS_IsExceptionPending(cx) &&
        !handle && native_admissions==admitted && next_wait==1 && imports.hasPending();
      JS_ClearPendingException(cx);
      limits[LATENT_RUNTIME_ACTIVATION_OWNER_KIND_NATIVE]=8;
      status=refused && imports.cancelAll(cx) && !imports.hasPending() ? 0:1;
    } else if (!std::strcmp(selected,"missing-import-record-reports-and-preserves-error")) {
      void* buffer = nullptr;
      JS::RootedObject promise(cx);
      bool reported = !imports.beginLowering(cx,999) && JS_IsExceptionPending(cx);
      JS_ClearPendingException(cx);
      reported = reported && !imports.started(cx,999,0,&promise) && JS_IsExceptionPending(cx);
      JS_ClearPendingException(cx);
      reported = reported && !imports.beginLifting(cx,999,buffer) && JS_IsExceptionPending(cx);
      JS_ClearPendingException(cx);
      reported = reported && !imports.liftValue(cx,999,&output) && JS_IsExceptionPending(cx);
      JS_ClearPendingException(cx);
      reported = reported && !imports.liftCompleted(cx,999) && JS_IsExceptionPending(cx);
      JS_ClearPendingException(cx);
      reported = reported && !imports.cancel(cx,999) && JS_IsExceptionPending(cx);
      JS_ClearPendingException(cx);
      JS::RootedValue original(cx,JS::Int32Value(42));
      JS_SetPendingException(cx,original);
      bool refused = !imports.liftCompleted(cx,999);
      JS::RootedValue retained(cx);
      status = reported && refused && JS_GetPendingException(cx,&retained) &&
               retained.isInt32() && retained.toInt32()==42 && !imports.hasPending() &&
               imported_starts==0 ? 0 : 1;
      JS_ClearPendingException(cx);
    } else if (!std::strcmp(selected,"real-import-Promise-pending-until-terminal")) {
      if(!evaluate(cx,"globalThis.answer=0;globalThis.root=ordinaryImported().then(liftImported).then(value=>{answer=value;rootDone();});",&output))return 10;
      status=imported_starts==1 && imported_lifts==0 && !expect(cx,"answer===42") &&
             shared_drain(cx,queue,timers,imports,readiness) && imported_lifts==1 && expect(cx,"answer===42")?0:1;
    } else if (!std::strcmp(selected,"parked-import-runnable-timer-and-microtask-sibling")) {
      block_import=true;
      if(!evaluate(cx,"globalThis.order=[];globalThis.root=ordinaryImported().then(liftImported).then(value=>{order.push(value);rootDone();});Promise.resolve().then(()=>order.push('microtask'));setTimeout(()=>{order.push('timer');releaseImported();},1);",&output))return 10;
      status=shared_drain(cx,queue,timers,imports,readiness) && imported_lifts==1 &&
             expect(cx,"order.join(',')==='microtask,timer,42'")?0:1;
    } else if (!std::strcmp(selected,"accepted-import-after-root-settlement")) {
      if(!evaluate(cx,"globalThis.answer=0;globalThis.root=ordinaryImported().then(liftImported).then(value=>{answer=value;});",&output) || !jobs.settleRoot(cx))return 10;
      status=shared_drain(cx,queue,timers,imports,readiness) && expect(cx,"answer===42")?0:1;
    } else if (!std::strcmp(selected,"opaque-import-not-lifted-on-close")) {
      if(!evaluate(cx,"globalThis.root=ordinaryImported();",&output) || !jobs.settleRoot(cx))return 10;
      status=!shared_drain(cx,queue,timers,imports,readiness) && imports.hasPending() &&
             imported_lifts==0 && counts[LATENT_RUNTIME_ACTIVATION_OWNER_KIND_RESULT]==1?0:1;
    } else if (!std::strcmp(selected,"cancel-keeps-import-buffer-until-terminal")) {
      defer_cancel=true;
      if(!evaluate(cx,"globalThis.root=ordinaryImported().catch(()=>rootDone());",&output))return 10;
      if(!imports.cancel(cx,1))return 10;
      const bool retained=counts[LATENT_RUNTIME_ACTIVATION_OWNER_KIND_RESULT]==1 &&
                          counts[LATENT_RUNTIME_ACTIVATION_OWNER_KIND_WAIT]==1;
      status=retained && shared_drain(cx,queue,timers,imports,readiness) && imported_lifts==0?0:1;
    } else if (!std::strcmp(selected,"typed-import-lift-finally-preserves-original-error")) {
      if(!evaluate(cx,"globalThis.message='';globalThis.root=ordinaryImported().then(id=>{try{const value=liftImported(id);if(value===42)throw new Error('original lift consumer failure');}finally{}}).catch(error=>{message=error.message;rootDone();});",&output))return 10;
      status=shared_drain(cx,queue,timers,imports,readiness) && imported_lifts==1 &&
             expect(cx,"message==='original lift consumer failure'")?0:1;
    } else if (!std::strcmp(selected, "snapshot-pure-promises-no-owner-imports")) {

      if (!jobs.parkRoot(cx) || !jobs.settleRoot(cx)) return 10;
      effects = false; compiler_phase = true;
      const auto before = host_calls;
      if (!evaluate(cx, "globalThis.answer=0;globalThis.order=['sync'];"
          "(async()=>{await Promise.resolve(40);return 42;})()"
          ".then(v=>{answer=v;order.push('micro');});", &output)) return 10;
      js::RunJobs(cx);
      status = host_calls == before && queue.empty() && !queue.isDrainingStopped() &&
               !JS_IsExceptionPending(cx) && counts[LATENT_RUNTIME_ACTIVATION_OWNER_KIND_NATIVE] == 0 &&
               expect(cx, "answer===42&&order.join(',')==='sync,micro'") ? 0 : 1;
    } else if (!std::strcmp(selected, "snapshot-job-cannot-cross-activation")) {
      if (!jobs.parkRoot(cx) || !jobs.settleRoot(cx)) return 10;
      effects = false; compiler_phase = true;
      if (!evaluate(cx, "globalThis.called=0;Promise.resolve().then(()=>called++);", &output)) return 10;
      const auto before = host_calls;
      effects = true; compiler_phase = false;
      js::RunJobs(cx);
      const bool refused = queue.isDrainingStopped() && JS_IsExceptionPending(cx) &&
                           host_calls == before && counts[LATENT_RUNTIME_ACTIVATION_OWNER_KIND_TASK] == 0;
      JS_ClearPendingException(cx);
      effects = false; compiler_phase = true;
      status = refused && expect(cx, "called===0") && queue.cancelQueued(cx) ? 0 : 1;
    } else if (!std::strcmp(selected, "snapshot-runtime-effects-still-denied")) {
      if (!jobs.parkRoot(cx) || !jobs.settleRoot(cx)) return 10;
      effects = false; compiler_phase = true;
      const auto before = host_calls;
      const bool evaluated = evaluate(cx, "setTimeout(()=>42,0);", &output);
      status = !evaluated && JS_IsExceptionPending(cx) && host_calls == before &&
               starts == 0 && !timers.hasPending() ? 0 : 1;
    } else if (!std::strcmp(selected, "snapshot-opaque-promise-detected")) {
      if (!jobs.parkRoot(cx) || !jobs.settleRoot(cx)) return 10;
      effects = false; compiler_phase = true;
      const auto before = host_calls;
      if (!evaluate(cx, "globalThis.root=new Promise(()=>{});root.then(()=>42);", &output)) return 10;
      status = promises.hasPendingPromises() && reactions.hasPendingReactions() && queue.empty() &&
               host_calls == before && counts[LATENT_RUNTIME_ACTIVATION_OWNER_KIND_NATIVE] == 0 ? 0 : 1;
    } else if (!std::strcmp(selected, "root-promise-suspends")) {
      if (!evaluate(cx, "globalThis.answer=0;globalThis.root=new Promise(resolve=>"
          "{setTimeout(()=>resolve(42),0);});root.then(value=>{answer=value;rootDone();});", &output))
        return 10;
      if (!jobs.parkRoot(cx)) return 10;
      const bool pending = promises.hasPendingPromises() && !jobs.rootSettled() &&
                           timers.hasPending() && waits_entered == 0 && expect(cx, "answer===0");
      status = pending && drain(cx, queue, timers) && jobs.rootSettled() &&
               expect(cx, "answer===42") && waits_entered == 1 ? 0 : 1;
    } else if (!std::strcmp(selected, "macro-microtask-order")) {
      if (!evaluate(cx, "globalThis.order=['sync'];"
          "setTimeout(()=>{order.push('timer-a');Promise.resolve().then(()=>order.push('micro'));},0);"
          "setTimeout(()=>order.push('timer-b'),0);", &output) ||
          !jobs.parkRoot(cx) || !jobs.settleRoot(cx)) return 10;
      status = drain(cx, queue, timers) &&
               expect(cx, "order.join(',')==='sync,timer-a,micro,timer-b'") ? 0 : 1;
    } else if (!std::strcmp(selected, "accepted-timer-after-root")) {
      if (!evaluate(cx, "globalThis.called=0;setTimeout(()=>{called++;"
          "setTimeout(()=>{called++;},0);},0);", &output) ||
          !jobs.parkRoot(cx) || !jobs.settleRoot(cx)) return 10;
      status = jobs.rootSettled() && drain(cx, queue, timers) && starts == 2 &&
               expect(cx, "called===2") ? 0 : 1;
    } else if (!std::strcmp(selected, "captured-arguments")) {
      if (!evaluate(cx, "globalThis.answer=0;setTimeout((a,b)=>{answer=a.value+b;},0,{value:40},2);",
          &output) || !jobs.parkRoot(cx) || !jobs.settleRoot(cx)) return 10;
      collect(cx);
      status = drain(cx, queue, timers) && expect(cx, "answer===42") ? 0 : 1;
    } else if (!std::strcmp(selected, "clear-before-readiness")) {
      if (!evaluate(cx, "globalThis.called=0;globalThis.id=setTimeout(()=>called++,0);clearTimeout(id);",
          &output) || !jobs.parkRoot(cx) || !jobs.settleRoot(cx)) return 10;
      status = drain(cx, queue, timers) && drops == 1 && waits_entered == 0 &&
               expect(cx, "called===0") ? 0 : 1;
    } else if (!std::strcmp(selected, "clear-after-ready-before-callback")) {
      if (!evaluate(cx, "globalThis.called=0;globalThis.id=setTimeout(()=>called++,0);",
          &output) || !jobs.parkRoot(cx) || !jobs.settleRoot(cx)) return 10;
      if (!timers.turn(cx, true)) return 10; // actual readiness, no callback turn yet
      const bool pending = expect(cx, "called===0");
      if (!evaluate(cx, "clearTimeout(id);", &output)) return 10;
      status = pending && drain(cx, queue, timers) && drops == 1 &&
               expect(cx, "called===0") ? 0 : 1;
    } else if (!std::strcmp(selected, "coalesced-interval-self-clear")) {
      if (!evaluate(cx, "globalThis.called=0;globalThis.id=setInterval(()=>{called++;"
          "if(called===2)clearInterval(id);},0);", &output) ||
          !jobs.parkRoot(cx) || !jobs.settleRoot(cx)) return 10;
      status = drain(cx, queue, timers) && starts == 1 && observed_period == 1000000 &&
               drops == 2 && expect(cx, "called===2") ? 0 : 1;
    } else if (!std::strcmp(selected, "callback-exception-preserved")) {
      if (!evaluate(cx, "globalThis.called=0;globalThis.err=new Error('timer sentinel');"
          "setTimeout(()=>{called++;throw err;},0);", &output) ||
          !jobs.parkRoot(cx) || !jobs.settleRoot(cx)) return 10;
      const bool returned = drain(cx, queue, timers);
      JS::RootedValue exception(cx), expected(cx);
      const bool caught = JS_GetPendingException(cx, &exception);
      JS_ClearPendingException(cx);
      if (!JS_GetProperty(cx, global, "err", &expected)) return 10;
      status = !returned && caught && exception.isObject() && expected.isObject() &&
               &exception.toObject() == &expected.toObject() &&
               counts[LATENT_RUNTIME_ACTIVATION_OWNER_KIND_TASK] == 0 &&
               expect(cx, "called===1") ? 0 : 1;
    } else if (!std::strcmp(selected, "immediate-return-no-subtask-handle")) {
      immediate_return = true;
      if (!evaluate(cx, "globalThis.called=0;setTimeout(()=>called++,0);",
          &output) || !jobs.parkRoot(cx) || !jobs.settleRoot(cx)) return 10;
      status = drain(cx, queue, timers) && expect(cx, "called===1") &&
               drops == 0 && set_drops == 0 && waits_entered == 0 &&
               native_admissions == 1 ? 0 : 1;
    } else if (!std::strcmp(selected, "native-exhaustion-before-timer")) {
      limits[LATENT_RUNTIME_ACTIVATION_OWNER_KIND_NATIVE] = 0;
      const bool evaluated = evaluate(cx, "setTimeout(()=>42,0);", &output);
      status = !evaluated && JS_IsExceptionPending(cx) && starts == 0 &&
               native_admissions == 0 && next_wait == 1 && !timers.hasPending() ? 0 : 1;
    } else if (!std::strcmp(selected, "readiness-set-requires-actual-child-drop")) {
      latent_runtime_activation_token_t token{};
      latent_runtime_activation_error_t error{};
      latent_runtime_activation_result_u64_error_t result{};
      ReadinessSet readiness(native);
      Subtask next;
      if (!latent_runtime_activation_timer_start(0, nullptr, nullptr, &token, &error) ||
          !next.started(cx, latent_runtime_activation_timer_next(token, &result)) ||
          !readiness.join(cx, next)) return 10;
      const bool early_drop = readiness.retire(cx);
      const bool held = !early_drop && JS_IsExceptionPending(cx) && set_live &&
                        next.physical() && drops == 0 && set_drops == 0 &&
                        counts[LATENT_RUNTIME_ACTIVATION_OWNER_KIND_NATIVE] == 1;
      JS_ClearPendingException(cx);
      if (!latent_runtime_activation_timer_stop(&token, &error) ||
          !next.cancel(cx) || !next.drop(cx) || !readiness.retire(cx)) return 10;
      status = held && !next.physical() && !readiness.physical() &&
               drops == 1 && set_drops == 1 ? 0 : 1;
    } else if (!std::strcmp(selected, "timer-exhaustion-before-capture")) {
      limits[LATENT_RUNTIME_ACTIVATION_OWNER_KIND_TIMER] = 0;
      const bool evaluated = evaluate(cx, "globalThis.called=0;setTimeout(()=>called++,0);", &output);
      status = !evaluated && JS_IsExceptionPending(cx) && starts == 0 && next_wait == 1 &&
               counts[LATENT_RUNTIME_ACTIVATION_OWNER_KIND_TIMER] == 0 ? 0 : 1;
    } else if (!std::strcmp(selected, "snapshot-no-effects")) {
      effects = false;
      const bool evaluated = evaluate(cx, "setTimeout(()=>42,0);", &output);
      status = !evaluated && JS_IsExceptionPending(cx) && starts == 0 &&
               native_admissions == 0 && !timers.hasPending() ? 0 : 1;
      effects = true;
    } else if (!std::strcmp(selected, "cancel-retains-buffer-until-terminal")) {
      defer_cancel = true;
      if (!evaluate(cx, "globalThis.called=0;globalThis.id=setTimeout(()=>called++,0);clearTimeout(id);",
          &output) || !jobs.parkRoot(cx) || !jobs.settleRoot(cx)) return 10;
      const bool held = drops == 0 && waits[1].live && waits[1].result &&
                        counts[LATENT_RUNTIME_ACTIVATION_OWNER_KIND_NATIVE] >= 2 &&
                        expect(cx, "called===0");
      status = held && drain(cx, queue, timers) && drops == 1 &&
               expect(cx, "called===0") ? 0 : 1;
      defer_cancel = false;
    } else if (!std::strcmp(selected, "stop-ack-retains-owners")) {
      if (!evaluate(cx, "globalThis.called=0;globalThis.id=setTimeout(()=>called++,0);",
          &output) || !jobs.parkRoot(cx) || !jobs.settleRoot(cx)) return 10;
      refuse_stop = true;
      const bool cleared = evaluate(cx, "clearTimeout(id);", &output);
      status = !cleared && JS_IsExceptionPending(cx) && timers.hasPending() && drops == 0 &&
               counts[LATENT_RUNTIME_ACTIVATION_OWNER_KIND_TIMER] == 1 &&
               counts[LATENT_RUNTIME_ACTIVATION_OWNER_KIND_NATIVE] == 2 ? 0 : 1;
      refuse_stop = false;
    } else if (!std::strcmp(selected, "callback-ack-no-replay")) {
      if (!evaluate(cx, "globalThis.called=0;setTimeout(()=>called++,0);",
          &output) || !jobs.parkRoot(cx) || !jobs.settleRoot(cx)) return 10;
      if (!timers.turn(cx, true)) return 10;
      refuse_task_ack = true;
      const bool called = timers.turn(cx, true);
      status = !called && JS_IsExceptionPending(cx) &&
               counts[LATENT_RUNTIME_ACTIVATION_OWNER_KIND_TASK] == 1 &&
               timers.hasPending() ? 0 : 1;
      refuse_task_ack = false;
      JS_ClearPendingException(cx);
      if (!expect(cx, "called===1")) status = 1;
    }
    JS_ClearPendingException(cx);
    refuse_stop = refuse_task_ack = refuse_native_ack = defer_cancel = false;
    // Snapshot cleanup still carries no tenant tokens. Finish its actual weak
    // collection and queue retirement before changing the fixture phase.
    effects = !compiler_phase;
    if (!jobs.rootSettled() && !jobs.settleRoot(cx)) return 11;
    if (!timers.cancel(cx) || !imports.cancelAll(cx) || !queue.cancelQueued(cx) || !readiness.retire(cx)) return 11;
    output.setUndefined();
    if (!evaluate(cx, "globalThis.root=null;globalThis.order=null;globalThis.id=null;globalThis.answer=null;", &output))
      return 11;
    output.setUndefined();
    collect(cx);
    if (!reactions.checkpoint(cx) || !promises.checkpoint(cx)) return 11;
    effects = true; compiler_phase = false;
    unsigned total = 0; for (auto count : counts) total += count;
#ifdef LSF_TYPESCRIPT_BORROW_CONTROLS
    if(expected_quarantine) {
      for(uint64_t owner=1;owner<next_owner;++owner)
        if(owners[owner].live!=expected_retained[owner])status=1;
      if(!total || !drop_order_valid)status=1;
    } else
#endif
    if(total)status=1;
    if (timers.hasPending() || imports.hasPending() || !queue.empty() || set_live || host_in_gc) status = 1;
#ifdef LSF_TYPESCRIPT_BORROW_CONTROLS
    std::printf("{\"case\":\"%s\",\"status\":%d,\"owners\":%u,\"expectedQuarantine\":%s,"
                "\"subtaskDrops\":%u,\"cancelRequests\":%u,\"exactAckRefusals\":%u,"
                "\"recordDestroyed\":%s,\"observerDestroyed\":%s,\"dropOrderValid\":%s,"
                "\"managerBytes\":%zu,\"baselineManagerBytes\":%zu,\"fixedManagerDeltaBytes\":%zu,"
                "\"recordBytes\":%zu,\"observerBytes\":%zu,\"hostcallInGC\":%s}\n",
        selected,status,total,expected_quarantine?"true":"false",drops,cancel_requests,exact_refusals,
        record_destroyed?"true":"false",observer_destroyed?"true":"false",drop_order_valid?"true":"false",
        sizeof(Imports),sizeof(BorrowBaselineImports),sizeof(Imports)-sizeof(BorrowBaselineImports),
        ImportBorrowControls::recordBytes(),sizeof(ImportBorrowObserver),host_in_gc?"true":"false");
#else
    std::printf("{\"case\":\"%s\",\"status\":%d,\"owners\":%u,\"starts\":%u,\"stops\":%u,"
                "\"subtaskDrops\":%u,\"setDrops\":%u,\"idleWaits\":%u,\"nativeAdmissions\":%u,"
                "\"nativeAcknowledgements\":%u,\"hostcallInGC\":%s}\n",
        selected, status, total, starts, stops, drops, set_drops, waits_entered,
        native_admissions, native_acknowledgements, host_in_gc ? "true" : "false");
#endif
  }
  JS_DestroyContext(cx); JS_ShutDown(); return status;
}
