// Linked only into the explicit LSF Promise engine build. The ordinary engine
// and ordinary-value recipe do not include this translation unit.
#include "broker_accounting.h"
#include "native_engine.h"
#include "promise_accounting.h"
#include "promise_hooks.h"
#include "reaction_records.h"
#include "native_timers.h"
#include "extension-api.h"
#include "js/Prefs.h"
#include "jsfriendapi.h"

#include <memory>

namespace lsf::typescript::activation {

namespace {
bool effects_allowed(JSContext* cx) {
  auto* engine = api::Engine::get(cx);
  return engine && engine->state() == api::EngineState::Initialized;
}

BrokerPromiseAccounting::Phase promise_phase(JSContext* cx) {
  auto* engine = api::Engine::get(cx);
  if (!engine) return BrokerPromiseAccounting::Phase::Unavailable;
  switch (engine->state()) {
  case api::EngineState::EngineInitializing:
  case api::EngineState::ScriptPreInitializing:
    return BrokerPromiseAccounting::Phase::CompilerSnapshot;
  case api::EngineState::Initialized:
    return BrokerPromiseAccounting::Phase::Activation;
  default:
    return BrokerPromiseAccounting::Phase::Unavailable;
  }
}

bool compiler_snapshot_allowed(JSContext* cx) {
  return promise_phase(cx) == BrokerPromiseAccounting::Phase::CompilerSnapshot;
}

BrokerAccounting accounting(effects_allowed, compiler_snapshot_allowed);
BrokerPromiseAccounting promise_accounting(promise_phase, accounting);
PromiseRecords promises(promise_accounting);
ReactionRecords reactions(promise_accounting, accounting);
Timers timers(accounting, promise_accounting);
std::unique_ptr<JobQueue> queue;

bool before_promise_allocate(JSContext* cx, void** output) {
  return reactions.checkpoint(cx) && promises.checkpoint(cx) &&
         promises.beforeAllocate(cx, output);
}
bool before_reaction_allocate(JSContext* cx, void** output) {
  return reactions.checkpoint(cx) && promises.checkpoint(cx) &&
         reactions.beforeAllocate(cx, output);
}
void settled_promise(JSContext* cx, JSObject* promise) {
  promises.settled(cx, promise);
}
void* reaction_record(JSContext* cx, JSObject* reaction) {
  return reactions.record(cx, reaction);
}
void sweep_owned_objects(JSTracer* tracer, void*) {
  promises.sweep(tracer);
  reactions.sweep(tracer);
}
void complete_owned_collection(JS::GCContext*, JSFinalizeStatus status, void*) {
  if (status != JSFINALIZE_COLLECTION_END) return;
  promises.collectionCompleted();
  reactions.collectionCompleted();
}
bool transfer_reaction(JSContext* cx, JS::HandleObject job, JobOwners& owners,
                       bool& transferred) {
  void* record = nullptr;
  if (!JS::ActivationReactionRecordForJob(cx, job, &record)) return false;
  if (!record) return true;
  if (!reactions.transfer(cx, record, owners)) return false;
  transferred = true;
  return true;
}
const JS::ActivationPromiseHooks promise_hooks{
    before_promise_allocate, PromiseRecords::allocationFailed,
    PromiseRecords::created, settled_promise,
    before_reaction_allocate, ReactionRecords::allocationFailed,
    ReactionRecords::created, reaction_record,
    before_reaction_allocate, ReactionRecords::allocationFailed,
    ReactionRecords::created, reaction_record};
}

// Called before JS_Init. Firefox147 defaults to a second microtask queue that
// bypasses enqueuePromiseJob; that queue is not part of this explicit profile.
void configure_job_dispatch() {
  JS::Prefs::set_use_js_microtask_queue(false);
}

// Called after the engine's internal dispatch initialization. The queue and
// its rooted records live with this engine/Store, never in a tenant daemon.
bool install_job_dispatch(JSContext* cx) {
  if (queue) {
    JS_ReportErrorASCII(cx, "activation-runtime-job-queue-already-installed");
    return false;
  }
  queue.reset(new (std::nothrow) JobQueue(accounting, transfer_reaction));
  if (!queue) {
    JS_ReportOutOfMemory(cx);
    return false;
  }
  if (!JS_AddWeakPointerZonesCallback(cx, sweep_owned_objects, nullptr) ||
      !JS_AddFinalizeCallback(cx, complete_owned_collection, nullptr) ||
      !JS::SetActivationPromiseHooks(cx, &promise_hooks)) return false;
  JS::SetJobQueue(cx, queue.get());
  return true;
}

bool snapshot_jobs_empty(JSContext* cx) {
  if (!queue || !queue->empty() || queue->isDrainingStopped() ||
      api::Engine::has_pending_async_tasks() || timers.hasPending() || promises.hasPendingPromises() ||
      api::Engine::has_unhandled_promise_rejections() ||
      reactions.hasPendingReactions() || !reactions.checkpoint(cx) ||
      !promises.checkpoint(cx)) {
    JS_ReportErrorASCII(cx, "activation-runtime-pending-work-during-snapshot-denied");
    return false;
  }
  return true;
}

bool acknowledge_promise_retirement(JSContext* cx) {
  return reactions.checkpoint(cx) && promises.checkpoint(cx);
}

bool has_pending_promises() {
  return promises.hasPendingPromises();
}

bool cancel_job_dispatch(JSContext* cx) {
  const bool jobs_retired = queue && queue->cancelQueued(cx);
  const bool timers_retired = timers.cancel(cx);
  return jobs_retired && timers_retired;
}

bool start_timer(JSContext* cx, JS::HandleObject callback,
                 const JS::HandleValueArray& arguments, int32_t delay_ms,
                 bool repeat, int32_t* id) {
  if (!effects_allowed(cx)) {
    JS_ReportErrorASCII(cx, "activation-runtime-timer-during-snapshot-denied");
    return false;
  }
  return timers.start(cx, callback, arguments, delay_ms, repeat, id);
}

bool clear_timer(JSContext* cx, int32_t id) { return timers.clear(cx, id); }
bool start_timeout_nanoseconds(JSContext* cx, JS::HandleObject callback,
                               const JS::HandleValueArray& arguments,
                               uint64_t nanos, int32_t* id) {
  if (!effects_allowed(cx)) {
    JS_ReportErrorASCII(cx, "activation-runtime-timeout-during-snapshot-denied");
    return false;
  }
  return timers.startNanoseconds(cx, callback, arguments, nanos, nullptr, id);
}
bool has_pending_timer_work() { return timers.hasPending(); }

bool run_timer_turn(JSContext* cx) {
  if (!effects_allowed(cx) || !queue || !queue->empty() || queue->isDrainingStopped()) {
    JS_ReportErrorASCII(cx, "activation-runtime-timer-pump-with-eligible-jobs-denied");
    return false;
  }
  return timers.turn(cx, true);
}

bool begin_root(JSContext* cx) { return accounting.beginRoot(cx); }
bool park_root(JSContext* cx) { return accounting.parkRoot(cx); }
bool settle_root(JSContext* cx) { return accounting.settleRoot(cx); }

bool root_work_drained(JSContext* cx) {
  if (!effects_allowed(cx)) return snapshot_jobs_empty(cx);
  if (api::Engine::has_unhandled_promise_rejections()) {
    JS_ReportErrorASCII(cx, "activation-runtime-unhandled-promise-rejection-on-close");
    return false;
  }
  if (!queue || !queue->empty() || queue->isDrainingStopped() ||
      timers.hasPending() || !accounting.rootSettled()) {
    JS_ReportErrorASCII(cx, "activation-runtime-root-or-accepted-jobs-still-live");
    return false;
  }
  // Unreachable, unused Promises/reactions are not opaque pending work. Mark
  // their actual reachability and physical collection before checking drain;
  // live root/result/capture graphs retain their original native reservations.
  JS::PrepareForFullGC(cx);
  JS::NonIncrementalGC(cx, JS::GCOptions::Normal, JS::GCReason::API);
  if (!acknowledge_promise_retirement(cx)) return false;
  if (promises.hasPendingPromises() || reactions.hasPendingReactions() ||
      api::Engine::has_pending_async_tasks()) {
    JS_ReportErrorASCII(cx, "activation-runtime-opaque-pending-work-on-close");
    return false;
  }
  return true;
}

bool acknowledge_result_retirement(JSContext* cx) {
  // The original post_call has released lowering buffers and the call's native
  // rooted values. Reachable application graphs remain charged until the Store
  // physically retires; never claim their release merely because root settled.
  JS::PrepareForFullGC(cx);
  JS::NonIncrementalGC(cx, JS::GCOptions::Normal, JS::GCReason::API);
  return acknowledge_promise_retirement(cx);
}

} // namespace lsf::typescript::activation
