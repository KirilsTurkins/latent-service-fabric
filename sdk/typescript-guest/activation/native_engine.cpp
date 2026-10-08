// Linked only into the explicit LSF Promise engine build. The ordinary engine
// and ordinary-value recipe do not include this translation unit.
#include "broker_accounting.h"
#include "native_engine.h"
#include "promise_accounting.h"
#include "promise_hooks.h"
#include "reaction_records.h"
#include "native_timers.h"
#include "native_objects.h"
#include "native_imports.h"
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
NativeObjectRecords native_objects;
ReadinessSet readiness(promise_accounting);
Timers timers(accounting, promise_accounting, readiness);
Imports imports(accounting, promise_accounting, readiness);
std::unique_ptr<JobQueue> queue;

bool before_promise_allocate(JSContext* cx, void** output) {
  return acknowledge_promise_retirement(cx) &&
         promises.beforeAllocate(cx, output);
}
bool before_reaction_allocate(JSContext* cx, void** output) {
  return acknowledge_promise_retirement(cx) &&
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
  native_objects.collectionCompleted();
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
      native_objects.hasRetained() || imports.hasPending() || readiness.physical() ||
      reactions.hasPendingReactions() || !reactions.checkpoint(cx) ||
      !promises.checkpoint(cx)) {
    JS_ReportErrorASCII(cx, "activation-runtime-pending-work-during-snapshot-denied");
    return false;
  }
  return true;
}

bool acknowledge_promise_retirement(JSContext* cx) {
  return native_objects.checkpoint([cx](NativeOwner& owner) {
           return promise_accounting.acknowledgeRetirement(cx, owner) && !owner.live;
         }) && reactions.checkpoint(cx) && promises.checkpoint(cx);
}

bool admit_native_object(JSContext* cx, NativeObjectLease& lease) {
  // Mutable Abort/Event graphs carry invocation-local listeners/weak links.
  // They are never admitted while creating a shared compiler snapshot.
  if (!effects_allowed(cx) || native_objects.stopped()) {
    JS_ReportErrorASCII(cx, "activation-runtime-native-object-phase-or-admission-denied");
    return false;
  }
  if (!acknowledge_promise_retirement(cx)) return false;
  NativeOwner owner;
  if (!promise_accounting.beforeAllocate(cx, owner) || !owner.live) return false;
  NativeObjectRecords::Record* record = nullptr;
  if (!native_objects.track(owner, record)) {
    JS_ReportOutOfMemory(cx);
    return false;
  }
  if (!lease.bind(record)) {
    NativeObjectRecords::physicallyRetired(record);
    JS_ReportErrorASCII(cx, "activation-runtime-native-object-lease-reused");
    return false;
  }
  return true;
}

bool has_pending_promises() {
  return promises.hasPendingPromises();
}

bool cancel_job_dispatch(JSContext* cx) {
  const bool jobs_retired = queue && queue->cancelQueued(cx);
  const bool timers_retired = timers.cancel(cx);
  const bool imports_retired = imports.cancelAll(cx);
  return jobs_retired && timers_retired && imports_retired && readiness.retire(cx);
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
bool has_pending_timer_work() { return timers.hasPending() || imports.hasPending(); }

bool run_timer_turn(JSContext* cx) {
  if (!effects_allowed(cx) || !queue || !queue->empty() || queue->isDrainingStopped()) {
    JS_ReportErrorASCII(cx, "activation-runtime-timer-pump-with-eligible-jobs-denied");
    return false;
  }
  if (!imports.turn(cx) || !timers.turn(cx, false, false)) return false;
  if (!queue->empty() || imports.hasReady() || timers.callbackDispatched()) return true;
  if (readiness.hasJoined()) return readiness.dispatch(cx, true);
  if (imports.hasPending() || timers.hasPendingRecords()) {
    JS_ReportErrorASCII(cx, "activation-runtime-import-or-timer-without-readiness");
    return false;
  }
  return readiness.retire(cx);
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
      timers.hasPending() || imports.hasPending() || !accounting.rootSettled()) {
    JS_ReportErrorASCII(cx, "activation-runtime-root-or-accepted-jobs-still-live");
    return false;
  }
  // Unreachable, unused Promises/reactions are not opaque pending work. Mark
  // their actual reachability and physical collection before checking drain;
  // live root/result/capture graphs retain their original native reservations.
  JS::PrepareForFullGC(cx);
  JS::NonIncrementalGC(cx, JS::GCOptions::Normal, JS::GCReason::API);
  if (!acknowledge_promise_retirement(cx)) return false;
  if (native_objects.hasUnacknowledgedRetirement()) {
    JS_ReportErrorASCII(cx, "activation-runtime-native-object-retirement-not-acknowledged");
    return false;
  }
  if (promises.hasPendingPromises() || reactions.hasPendingReactions() ||
      api::Engine::has_pending_async_tasks()) {
    JS_ReportErrorASCII(cx, "activation-runtime-opaque-pending-work-on-close");
    return false;
  }
  return true;
}

bool reserve_import(JSContext* cx, uint32_t result_size, uint32_t parameter_size,
                    uint32_t raw_kind, const JS::HandleValueArray& captures, uint32_t* id, void** result, void** parameters) {
  if (!effects_allowed(cx) || !acknowledge_promise_retirement(cx)) {
    JS_ReportErrorASCII(cx, "activation-runtime-import-during-snapshot-denied");
    return false;
  }
  if (raw_kind > static_cast<uint32_t>(ImportRawResult::U16)) {
    JS_ReportErrorASCII(cx,"activation-runtime-import-result-kind-invalid"); return false;
  }
  if (!imports.reserve(cx, result_size, parameter_size, static_cast<ImportRawResult>(raw_kind), captures, *id)) return false;
  *result = imports.resultBuffer(*id);
  *parameters = imports.parameterBuffer(*id);
  return true;
}
bool begin_import_lowering(JSContext* cx, uint32_t id) { return imports.beginLowering(cx, id); }
void* import_result_buffer(uint32_t id) { return imports.resultBuffer(id); }
void* import_parameter_buffer(uint32_t id) { return imports.parameterBuffer(id); }
bool start_import(JSContext* cx, uint32_t id, uint32_t status, JS::MutableHandleObject promise) {
  return imports.started(cx, id, status, promise);
}
bool lift_import(JSContext* cx, uint32_t id, void** result) {
  return imports.beginLifting(cx, id, *result);
}
bool lift_import_value(JSContext* cx, uint32_t id, JS::MutableHandleValue value) {
  return imports.liftValue(cx,id,value);
}
bool finish_import(JSContext* cx, uint32_t id) { return imports.liftCompleted(cx, id); }
bool cancel_import(JSContext* cx, uint32_t id) { return imports.cancel(cx, id); }

bool acknowledge_result_retirement(JSContext* cx) {
  // The original post_call has released lowering buffers and the call's native
  // rooted values. Reachable application graphs remain charged until the Store
  // physically retires; never claim their release merely because root settled.
  JS::PrepareForFullGC(cx);
  JS::NonIncrementalGC(cx, JS::GCOptions::Normal, JS::GCReason::API);
  return acknowledge_promise_retirement(cx);
}

} // namespace lsf::typescript::activation
